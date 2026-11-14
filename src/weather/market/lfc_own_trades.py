"""Canonical own executions keyed by venue trade ID and our exact order ID.

Lifecycle/provenance are explicit. Reconciliation retains the historical money
rule: every non-FAILED execution counts, including provisional evidence.
Terminal order reads still own reserve release and booked cost basis.
"""
from copy import deepcopy
from decimal import Decimal

from weather.market.lfc_accounting import quantity
from weather.market.mm_stage2_hold import digest


FINAL = {'CONFIRMED', 'FAILED'}
RANK = {'': 0, 'MATCHED': 1, 'RETRYING': 1, 'MINED': 2, 'CONFIRMED': 3, 'FAILED': 3}


def execution_rows(trade, ours):
    """Use our maker row's price/amount, never the parent taker's price/size."""
    payload = trade.get('payload')
    if isinstance(payload, dict):
        yield from execution_rows(payload, ours)
    elif trade.get('official_event_type') == 'trade':
        oid = str(trade.get('order_id') or '')
        if oid in ours and trade.get('fill_size') is not None:
            yield oid, {'price': trade.get('fill_price'), 'shares': trade['fill_size'],
                'token_id': trade.get('clob_token_id'), 'condition_id': trade.get('condition_id'),
                'side': trade.get('side'), 'liquidity_role': trade.get('liquidity_role', 'MAKER')}
    else:
        oid = str(trade.get('taker_order_id') or '')
        if oid in ours:
            yield oid, {'price': trade.get('price'), 'shares': trade.get('size', 0),
                'token_id': trade.get('asset_id', trade.get('token_id')), 'condition_id': trade.get('market'),
                'side': trade.get('side'), 'liquidity_role': 'TAKER'}
        for maker in trade.get('maker_orders') or ():
            oid = str(maker.get('order_id') or '')
            if oid in ours:
                yield oid, {'price': maker.get('price'), 'shares': maker.get('matched_amount', 0),
                    'token_id': maker.get('asset_id', maker.get('token_id')), 'condition_id': trade.get('market'),
                    'side': maker.get('side'), 'liquidity_role': 'MAKER'}


class OwnTradeProjection:
    def __init__(self, *, limit=50000):
        self.records, self.limit = {}, limit
        self.new_keys = set()

    def ingest(self, trades, ours, *, source, observed_at_utc=None):
        if source not in {'stream', 'rest'}:
            raise ValueError('own_trade_source')
        self.new_keys = set()
        changed = {}
        for trade in trades:
            payload = trade.get('payload') if isinstance(trade.get('payload'), dict) else trade
            status = str(payload.get('official_trade_status', payload.get('status', '')) or '').upper()
            tid = payload.get('trade_id', payload.get('id'))
            identity = 'venue_trade_id'
            if tid is None:
                # Old retained fixtures/legacy records have no venue trade ID.
                # Name that limitation; never invent a venue identity or size split.
                tid, identity = 'legacy:' + digest(payload), 'legacy_content_sha256'
            if not isinstance(tid, str) or not tid.strip() or len(tid) > 256:
                raise ValueError('own_trade_identity')
            for oid, execution in execution_rows(trade, ours):
                key = tid, oid
                meta = ours.get(oid, {}) if isinstance(ours, dict) else {}
                price = execution['price'] if execution['price'] is not None else meta.get('price')
                row = {'trade_id': tid, 'own_order_id': oid, 'identity_basis': identity,
                    **{name: execution.get(name) or meta.get(name) for name in ('token_id', 'condition_id', 'side')},
                    'liquidity_role': execution['liquidity_role'],
                    'price': str(quantity(price)) if price is not None else None,
                    'shares': str(quantity(execution['shares'])), 'status': status,
                    'state': 'confirmed' if status == 'CONFIRMED' else 'failed' if status == 'FAILED' else 'provisional',
                    'final': status in FINAL, 'money_counted': status != 'FAILED',
                    'transaction_hash': payload.get('transaction_hash'),
                    'exchange_match_time': payload.get('exchange_match_time', payload.get('match_time'))}
                old = self.records.get(key)
                if old is not None:
                    for name in ('shares', 'price', 'token_id', 'condition_id', 'side', 'liquidity_role'):
                        if old.get(name) is not None and row.get(name) is not None:
                            same = (quantity(old[name]) == quantity(row[name]) if name in {'shares', 'price'}
                                    else old[name] == row[name])
                            if not same:
                                raise ValueError('own_trade_conflict')
                    if old['final'] and row['final'] and old['status'] != status:
                        raise ValueError('own_trade_final_conflict')
                    if RANK.get(old['status'], 0) > RANK.get(status, 0):
                        row.update({name: old[name] for name in ('status', 'state', 'final', 'money_counted')})
                    for name, value in old.items():
                        if row.get(name) is None:
                            row[name] = value
                elif len(self.records) >= self.limit:
                    raise ValueError('own_trade_record_budget')
                else:
                    self.new_keys.add(key)
                provenance = deepcopy(old['provenance']) if old is not None else []
                bucket = status if status in RANK else 'OTHER'
                proof = next((p for p in provenance if p['source'] == source and p['status'] == bucket), None)
                if proof is None:
                    proof = {'source': source, 'status': bucket, 'first_observed_at_utc': observed_at_utc}
                    provenance.append(proof)
                proof.update(last_observed_at_utc=observed_at_utc,
                             raw_sha256=trade.get('raw_event_sha256') or digest(payload))
                row['provenance'] = provenance
                self.records[key] = row
                # Repeated reads update bounded provenance, not an append-only cache.
                if old is None or any(row.get(name) != old.get(name) for name in row if name != 'provenance') or len(provenance) != len(old['provenance']):
                    changed[key] = row
        return deepcopy(list(changed.values()))

    def rows(self):
        return deepcopy([row for _, row in sorted(self.records.items())])

    def traded_shares(self):
        totals = {}
        for row in self.records.values():
            if row['money_counted']:
                oid = row['own_order_id']
                totals[oid] = totals.get(oid, Decimal(0)) + quantity(row['shares'])
        return {oid: str(size) for oid, size in sorted(totals.items())}
