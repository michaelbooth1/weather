"""Inert RE-1M exchange layered on 80b's MemoryVenue and public book reader."""
from copy import deepcopy
from datetime import datetime, timezone
import time

from weather.market.mm_stage2_selection import PublicBooks


class WallClock:
    realtime = True
    def now(self): return datetime.now(timezone.utc)
    def monotonic(self): return time.monotonic()
    def sleep(self, seconds): time.sleep(seconds)


class Re1PublicBooks(PublicBooks):
    def get(self, url, **kwargs):
        value = super().get(url, **kwargs)
        if hasattr(self, '_snapshot_reads'):
            self._snapshot_reads.append({'url': url, 'payload': value})
        return value

    def snapshot(self, condition, tokens, *, reward=None, checkpoint=lambda: None):
        self._snapshot_reads = []
        try:
            reward = self.reward(condition, checkpoint=checkpoint) if reward is None else reward
            result = super().snapshot(condition, tokens, reward=reward, checkpoint=checkpoint)
            result['reward_record'] = reward
            result['raw_public_responses'] = self._snapshot_reads
            return result
        finally:
            del self._snapshot_reads


class RehearsalVenue:
    def __init__(self, snapshot, directory, *, clock, public=None):
        from weather.market.mm_stage2_rehearsal import MemoryVenue, MAKER
        from weather.market.re1_attended import HOST
        self.host, self.maker = HOST, MAKER
        self.memory = MemoryVenue(snapshot, directory)
        self.memory.clock = clock
        self.public = public
        self.calls = []

    def snapshot(self, condition, tokens, *, checkpoint=lambda: None):
        if self.public is not None:
            self.memory.public_input = self.public.snapshot(condition, tokens, checkpoint=checkpoint)
        return self.memory.snapshot(checkpoint=checkpoint)

    def open_orders(self):
        return deepcopy([r for r in self.memory.orders.values() if r['status'] == 'LIVE'])

    def order(self, oid): return deepcopy(self.memory.orders[oid])
    def events(self): return []
    def trades(self): return []
    def positions(self): return []
    def geography(self): return {'blocked': False, 'simulated': True}
    def heartbeat(self): return {'status': 'ok'}
    def balances(self):
        return {'available_collateral': '50', 'assets': {'candidate_asset_a': '50', 'candidate_asset_b': '0'},
                'simulated': True}
    def scoring(self, ids): return dict.fromkeys(ids, True)
    def accrual(self, day): return {'day': day, 'rows': [], 'simulated': True}

    def submit(self, request, *, checkpoint=lambda: None):
        checkpoint()
        if hasattr(self, 'before_post'):
            self.before_post(request)
        self.calls.append(deepcopy(request))
        oid = f'rehearsal-order-{len(self.memory.orders) + 1}'
        self.memory.orders[oid] = {'id': oid, 'asset_id': request['token_id'], 'market': self.memory.condition,
            'maker_address': self.maker, 'side': request['side'], 'price': request['price'],
            'original_size': request['size'], 'size_matched': '0', 'status': 'LIVE', 'associate_trades': [],
            'expiration': request['expiration']}
        return {'ok': True, 'order_id': oid, 'status': 'live', 'trade_ids': []}

    def cancel(self, oid):
        self.memory.orders[oid]['status'] = 'CANCELED'
        return {'canceled': [oid], 'not_canceled': {}}

    def cancel_all(self):
        ids = [r['id'] for r in self.open_orders()]
        for oid in ids: self.cancel(oid)
        return {'canceled': ids, 'not_canceled': {}}
