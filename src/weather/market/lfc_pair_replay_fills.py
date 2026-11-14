"""Verify copied A091 fill inputs against K6 and the campaign's held own lots."""
from decimal import Decimal
import re

from weather.market.lfc_accounting import quantity
from weather.market.lfc_capital import CapitalBook, native
from weather.market.lfc_ledger import Ledger
from weather.market.lfc_pair_inventory import project_read, held_inventory
from weather.market.lfc_pair_completion import instant
from weather.market.lfc_recording_io import strict_json


TRADE_EVENTS = frozenset({'user_events', 'repost_user_events', 'fill', 'terminal_trades'})
TRADE_LINE = re.compile(r'"event"\s*:\s*"(?:'+'|'.join(sorted(TRADE_EVENTS))+')"')


def session_directories(receipts, sessions):
    """A091 CSV uses short session IDs; resolve only an unambiguous copy."""
    result = {}
    for prefix in sessions:
        candidates = {key.split('/')[0] for key in receipts
                      if key.startswith('session-F2-'+prefix) and key.endswith('/f2_manifest.json')}
        if len(candidates) != 1:
            raise ValueError('replay_session_binding')
        result[prefix] = candidates.pop()
    return result


def verify_fills(inputs, fills, bands, *, campaign_id):
    """Read only hashed copies. Geography journal events are never decoded."""
    ledger = Ledger.open(inputs.path('ledger.jsonl'), clock=lambda: instant('2026-11-13T23:45:00Z'))
    legs = {oid: dict(ledger.legs[key], intent_key=key, side='BUY') for oid, key in ledger.by_order.items()}
    directories = session_directories(inputs.receipts, {fill['session'] for fill in fills})
    from weather.market.lfc_own_trades import OwnTradeProjection
    projection, packets = OwnTradeProjection(), []
    journals = sorted({key for key in inputs.receipts if key.endswith('/journal.jsonl') and
                       key.split('/')[0] in directories.values()})
    for relative in journals:
        with inputs.path(relative).open(encoding='utf-8') as stream:
            for line in stream:
                if TRADE_LINE.search(line):
                    row = strict_json(line)
                    event = row['event']
                    if event not in TRADE_EVENTS:
                        continue
                    trades = ([row['user_event']] if row.get('user_event') else []) if event == 'fill' else row.get('rows', [])
                    packets.append((row['recorded_at_utc'], 'rest' if event == 'terminal_trades' else 'stream', trades))
    for observed, source, trades in sorted(packets, key=lambda packet: packet[0]):
        project_read(trades, legs, observed_at_utc=observed, projection=projection, source=source)
    records = projection.rows()
    selected = { (fill['trade_id'], fill['order_id']): fill for fill in fills }
    canonical = { (row['trade_id'], row['own_order_id']): row for row in records
                  if (row['trade_id'], row['own_order_id']) in selected and row['money_counted'] }
    if canonical.keys() != selected.keys() or len(selected) != len(fills):
        raise ValueError('replay_canonical_fill_coverage')
    for key, fill in selected.items():
        row = canonical[key]
        checks = {'shares': (quantity(row['shares']), quantity(fill['size'])),
            'native_cost': (native(quantity(row['price'])*quantity(row['shares']), ceil=True),
                            native(quantity(fill['price'])*quantity(fill['size']), ceil=True)),
            'token_id': (row['token_id'], fill['token_id']), 'status': (row['status'], fill['status'])}
        differences = {name: tuple(map(str, values)) for name, values in checks.items() if values[0] != values[1]}
        if differences:
            raise ValueError('replay_canonical_fill_mismatch:' + str(differences))
    states = {}
    for fill in fills:
        band = bands[(fill['session'], fill['band'])]
        condition = band['condition_id']
        if condition in states:
            continue
        selections = [key for key in inputs.receipts if key.startswith(directories[fill['session']]+'/')
                      and key.endswith('/'+fill['band']+'/selection.json')]
        if len(selections) != 1:
            raise ValueError('replay_selection_coverage')
        selection = strict_json(inputs.path(selections[0]).read_text(encoding='utf-8-sig'))
        tokens = tuple(next(row['token_ids'] for row in selection['rows'] if row['condition_id'] == condition))
        state = held_inventory(records, legs, CapitalBook(ledger).lots, campaign_id=campaign_id,
                               condition_id=condition, tokens=tokens)
        states[condition] = state.evidence()
    return {'verified': True, 'trades': len(canonical),
            'orders': len({row['own_order_id'] for row in canonical.values()}),
            'shares': str(sum((quantity(row['shares']) for row in canonical.values()), Decimal(0))),
            'records': list(canonical.values()), 'held_inventory': states}
