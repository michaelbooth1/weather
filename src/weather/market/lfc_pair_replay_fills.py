"""Verify copied A091 fill inputs against K6 and the campaign's held own lots."""
from decimal import Decimal
import re

from weather.market.lfc_accounting import quantity
from weather.market.lfc_capital import CapitalBook, native
from weather.market.lfc_ledger import Ledger
from weather.market.lfc_pair_inventory import project_read, held_inventory
from weather.market.lfc_recording_io import strict_json


TERMINAL = re.compile(r'"event"\s*:\s*"terminal_trades"')


def verify_fills(inputs, fills, bands, *, campaign_id):
    """Read only hashed copies. Geography journal events are never decoded."""
    ledger = Ledger.open(inputs.path('ledger.jsonl'))
    legs = {oid: dict(ledger.legs[key], intent_key=key, side='BUY') for oid, key in ledger.by_order.items()}
    trades, observed = [], None
    journals = sorted({key for key in inputs.receipts if key.endswith('/journal.jsonl') and any(
        key.startswith('session-F2-'+fill['session']+'/') for fill in fills)})
    for relative in journals:
        with inputs.path(relative).open(encoding='utf-8') as stream:
            for line in stream:
                if TERMINAL.search(line):
                    row = strict_json(line)
                    trades.extend(row['rows'])
                    observed = max(observed or row['recorded_at_utc'], row['recorded_at_utc'])
    records = project_read(trades, legs, observed_at_utc=observed)
    selected = { (fill['trade_id'], fill['order_id']): fill for fill in fills }
    canonical = { (row['trade_id'], row['own_order_id']): row for row in records
                  if (row['trade_id'], row['own_order_id']) in selected and row['money_counted'] }
    if canonical.keys() != selected.keys() or len(selected) != len(fills):
        raise ValueError('replay_canonical_fill_coverage')
    for key, fill in selected.items():
        row = canonical[key]
        if (quantity(row['shares']) != quantity(fill['size']) or
                native(quantity(row['price'])*quantity(row['shares']), ceil=True) !=
                native(quantity(fill['price'])*quantity(fill['size']), ceil=True) or row['token_id'] != fill['token_id'] or
                row['status'] != fill['status']):
            raise ValueError('replay_canonical_fill_mismatch')
    states = {}
    for fill in fills:
        band = bands[(fill['session'], fill['band'])]
        condition = band['condition_id']
        if condition in states:
            continue
        selections = [key for key in inputs.receipts if key.startswith('session-F2-'+fill['session']+'/')
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
