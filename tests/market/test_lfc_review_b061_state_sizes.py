"""Guards: B061 retained state capacity through Dec31, twelve bands per day.

Synthetic SDK shapes only. No account, venue, credential or tape reads.
"""
from datetime import date
import json

import pytest

from weather.market.lfc_retained_cache import RetainedCache


def encoded_size(value):
    # Stream the encoder, including UTF-8 and escaping; never build a tape or
    # a campaign-sized serialized string merely to measure its length.
    return 1 + sum(len(part.encode('utf-8')) for part in json.JSONEncoder(
        sort_keys=True, separators=(',', ':'), allow_nan=False, default=str).iterencode(value))


def test_state_reader_accepts_late_campaign_file_above_sixteen_megabytes(tmp_path):
    path = tmp_path / 'synthetic-state.json'
    with path.open('w') as stream:
        stream.write('{"synthetic":"')
        for _ in range(17): stream.write('x' * 1_000_000)
        stream.write('"}')
    cache = RetainedCache()
    result = cache.json(path)
    assert len(result['synthetic']) == 17_000_000
    assert cache.bytes == 0  # No oversized deep copy just to evict it again.
    path.unlink()  # This generated input is reproducible; no live evidence.


def test_large_cache_entry_is_not_copied_before_immediate_eviction(tmp_path, monkeypatch):
    from weather.market import lfc_retained_cache as module
    path = tmp_path / 'small.json'; path.write_text('{}')
    cache = RetainedCache()
    monkeypatch.setattr(cache, 'signature', lambda path: ('stable', 1))
    monkeypatch.setattr(module, 'deepcopy', lambda value: pytest.fail('oversized cache copy'))
    value = {'synthetic': True}
    assert cache.get('test', path, lambda: (value, 17_000_000)) is value
    assert not cache.values and cache.bytes == 0


def test_large_go_packet_round_trips_the_actual_f2_private_proof(tmp_path, monkeypatch):
    from tests.market.test_lfc_f2_breadth_runtime import owner_runtime_fixture
    from weather.market.lfc_campaign_runtime import ScheduledAuthority
    from weather.market.mm_stage2_hold import digest
    ordinary = ScheduledAuthority.refresh_go
    def refresh(self, **kwargs):
        read = ordinary(self, **kwargs)
        read['synthetic_retained_extension'] = 'x' * 17_000_000
        self.go_proof['read_sha256'] = digest(read)
        return read
    monkeypatch.setattr(ScheduledAuthority, 'refresh_go', refresh)
    outcome = owner_runtime_fixture(tmp_path, monkeypatch, setup_latency=1)
    assert outcome['posts'] == 24 and not outcome['incidents']
    paths = list(tmp_path.glob('session-*/go_account.json'))
    assert len(paths) == 1 and paths[0].stat().st_size > 16_777_216
    paths[0].unlink()  # Regenerable fixture input, after full proof validation.


def test_every_cumulative_state_family_fits_dec31_projection(record_property):
    from polymarket.models.clob.account import ClobTrade, MakerOrder
    from weather.market.mm_official_adapter import plain_sdk_value
    from weather.market.lfc_recording_io import STATE_JSON_LIMIT, retained
    from weather.paths import REPO_ROOT
    days = (date(2026, 12, 31) - date(2026, 11, 9)).days + 1
    orders = days * 12 * 10  # Includes non-entry dates; no policy tightening.
    maker = '0x' + 'a' * 40
    token, condition = '9' * 77, '0x' + '1' * 64
    model = ClobTrade.model_validate(dict(id='t' * 64, market=condition, asset_id=token, owner='fixture',
        maker_address=maker, taker_order_id='o' * 64, side='SELL', trader_side='MAKER', price='.33', size='20',
        outcome='Yes', status='TRADE_STATUS_MATCHED', fee_rate_bps='0', bucket_index=0,
        transaction_hash='0x' + 'a' * 64, maker_orders=(MakerOrder.model_validate(dict(
            order_id='o' * 64, asset_id=token, maker_address=maker, owner='fixture', side='BUY',
            price='.33', matched_amount='20', outcome='Yes', fee_rate_bps='0')),),
        match_time=1800000000, last_update=1800000000))
    trade = plain_sdk_value(model)
    trade['synthetic_projection_padding'] = 'x' * max(0, 2048 - encoded_size(trade))
    source = json.loads((REPO_ROOT / 'tests/fixtures/lfc/paired_redeem_v2.json').read_text())
    activities = [{**source, 'transaction_hash': '0x' + f'{i:064x}'} for i in range(10000)]
    pages = [retained(json.dumps({'data': activities[i:i+500], 'pagination': {
        'has_more': i + 500 < len(activities), 'next_cursor': str(i+500) if i+500 < len(activities) else None}},
        separators=(',', ':')).encode()) for i in range(0, len(activities), 500)]
    allocations = [{'activity_id': f'{i:064x}', 'intent_key': 's' * 90 + str(i), 'quantity': '20',
        'cost_basis_released_native': 15800000, 'payout_native': 20000000,
        'returned_principal_native': 15800000} for i in range(orders)]
    redemptions = [{'activity_id': f'{i:064x}', 'cash_native': 20000000,
        'cost_basis_released_native': 15800000, 'returned_principal_native': 15800000,
        'outside_campaign': False, 'unallocated': []} for i in range(orders)]
    proof = {'inventory': {str(i): '20' for i in range(days * 12 * 2)},
             'capital': {'cost_basis_releases': allocations, 'redemptions': redemptions,
                 'zero_payout_losses': [{'intent_key': 's' * 90 + str(i), 'cost_basis_native': 15800000,
                     'settlement_sha256': 'c' * 64} for i in range(orders)]}}
    read = {'trades': [trade] * 25000, 'positions': [{'asset': token, 'conditionId': condition, 'size': '20'}] * (days*12*2),
        'capital_activity': {'rows': activities, 'pages': pages,
            'native_receipts': {r['transaction_hash']: {'native_group_sha256': 'b' * 64} for r in activities}}}
    bulky = encoded_size({'read': read, 'proof': proof})
    compact = encoded_size({'proof': proof, 'private_files': {f'band-{i}/file-{j}': 'a'*64 for i in range(12) for j in range(25)}})
    sizes = {name: bulky + 1_000_000 for name in (
        'account-reads', 'go-refreshes', 'prepared', 'postchecks', 'closed', 'owner-closures', 'go_account.json')}
    sizes.update({name: compact + 1_000_000 for name in ('results', 'economics', 'funding')})
    sizes.update({name: 1_000_000 for name in ('identity', 'claims', 'policies', 'incidents', 'skips', 'followups')})
    assert days == 53 and orders == 6360 and bulky > 16_777_216
    assert max(sizes.values()) < STATE_JSON_LIMIT, sizes
    record_property('projection', json.dumps({'days': days, 'bands_per_day': 12, 'max_orders': orders,
        'sdk_trade_rows': 25000, 'activity_rows': 10000, 'trade_bytes': encoded_size(trade),
        'state_limit_bytes': STATE_JSON_LIMIT, 'projected_bytes': sizes}, sort_keys=True))


def test_state_writer_refuses_oversize_before_publishing_unreadable_file(tmp_path, monkeypatch):
    from tests.market.test_lfc_campaign import MAKER, Mutexes, Clock, state_at
    from weather.market.lfc_campaign_guard import account_lease
    from weather.market import lfc_campaign_state as module
    with account_lease(MAKER, backend=Mutexes()):
        state = state_at(tmp_path, Clock())
        monkeypatch.setattr(module, 'STATE_JSON_LIMIT', 512)
        target = state.root / 'results' / 'too-large.json'
        with pytest.raises(ValueError, match='recording_file_budget'):
            state.save('results/too-large.json', {'synthetic': 'x' * 1024})
        assert not target.exists() and not list(target.parent.glob('.*.attempt-*'))
