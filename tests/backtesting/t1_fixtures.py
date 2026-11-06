"""Small synthetic International session; event date and D+2 are <= 2026-10-14."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import hashlib

from weather.backtesting.t1_accuracy import PIN_JOURNAL_VERSION, Tolerance
from weather.backtesting.t1_types import ReplayConfig, canonical

BASE = datetime(2026, 10, 12, 9, tzinfo=timezone.utc)


def at(seconds):
    return (BASE + timedelta(seconds=seconds)).isoformat()


def book(seconds=0, bid='.49', ask='.51', size='20', condition='c1'):
    side = {'bids': [{'price': bid, 'size': size, 'maker_id': 'competitor'}],
            'asks': [{'price': ask, 'size': size, 'maker_id': 'competitor'}], 'tick': '.01', 'min_order_size': '5'}
    return {'kind': 'book', 'condition_id': condition, 'at': at(seconds), 'observed_at': at(seconds),
            'source_sha256': 'e' * 64, 'reward_orders_complete': True,
            'reward_orders': [{'order_id': f'comp-{outcome}-{seconds}', 'maker_id': 'competitor', 'outcome': outcome,
                               'side': 'BUY', 'price': p, 'size': size}
                              for outcome, p in (('YES', bid), ('NO', str(1 - D(ask))))],
            'YES': side, 'NO': {'bids': [{'price': str(1 - D(ask)), 'size': size}],
                               'asks': [{'price': str(1 - D(bid)), 'size': size}],
                               'tick': '.01', 'min_order_size': '5'}}


def config(**changes):
    values = dict(informed_fraction='.75', latency_seconds='2', order_latency_seconds='1',
                  latency_source_sha256='a' * 64, measured_p95_seconds='2', measured_order_p95_seconds='1',
                  per_market_cap='50', total_cap='100', reward_epoch_rule='captured_active',
                  queue_rule='back_strict_through', competition_rule='maker_grouped',
                  max_book_age_seconds='600', markout_seconds=300, mark_max_delay_seconds='1',
                  fee_coefficient='.05', rebate_fraction='.25')
    return ReplayConfig(**{**values, **changes})


def payload():
    return {'start': at(0), 'end': at(306), 'opening_state': 'flat',
            'account_scope_complete': True, 'conditions': {'c1': {
        'venue': 'international_polymarket', 'token_ids': ['yes1', 'no1'], 'event_date': '2026-10-12',
        'native_unit': 'C', 'tick': '.01', 'min_order_size': '5',
        'coverage_start': at(0), 'coverage_end': at(306)}},
        'events': [book(), {'kind': 'terms', 'condition_id': 'c1', 'at': at(0), 'valid_until': at(307),
                            'min_size': '5', 'max_spread_cents': '3', 'rate_per_day': '864000',
                            'source_sha256': 'b' * 64},
                   {'kind': 'trade', 'condition_id': 'c1', 'at': at(4), 'traded_at': at(4), 'id': 't1',
                    'outcome': 'YES', 'aggressor': 'SELL', 'price': '.48', 'size': '25', 'source_sha256': 'f' * 64},
                   {'kind': 'trade', 'condition_id': 'c1', 'at': at(5), 'traded_at': at(5), 'id': 't2',
                    'outcome': 'YES', 'aggressor': 'SELL', 'price': '.48', 'size': '5', 'source_sha256': 'f' * 64},
                   book(304, '.45', '.47'), book(305, '.45', '.47'), book(306, '.45', '.47'),
                   {'kind': 'settlement', 'condition_id': 'c1', 'at': at(306), 'yes_payout': '1',
                    'source': 'venue', 'source_sha256': 'c' * 64}],
        'commands': [{'kind': 'post', 'id': 'o1', 'condition_id': 'c1', 'outcome': 'YES',
                      'observed_at': at(0), 'decided_at': at(0), 'expires_at': at(60), 'price': '.49', 'size': '10'}],
        'rebate_pools': {'2026-10-12': {'category': 'weather', 'complete': True,
                                       'source_sha256': 'd' * 64, 'total_taker_fees': '10',
                                       'total_maker_fee_weight': '10'}},
        'reward_epochs': {'2026-10-12': {'c1': {'active_seconds': '86400', 'complete': True,
                                              'source_sha256': 'a' * 64}}}}


def journal_bytes(events=None):
    if events is None:
        events = [(0, 'opened', {'scope': {'condition_id': 'c1', 'token_ids': ['yes1', 'no1'],
                                         'maker_address': 'synthetic-account', 'session_id': 'synthetic-session'},
                                  'mode': 'replay', 'profile_sha256': 'e' * 64}),
                  (0, 'submit_market_snapshot', {'snapshot': {'condition_id': 'c1',
                      'token_ids': ['yes1', 'no1'], 'observed_at_utc': at(0)}}),
                  (1, 'submit_request', {'request': {'token_id': 'yes1', 'side': 'BUY',
                      'price': '.49', 'size': '10', 'post_only': True, 'expiration': int((BASE + timedelta(seconds=60)).timestamp())}}),
                  (2, 'submit_response', {'response': {'orderID': 'o1', 'success': True, 'status': 'live'}}),
                  (2, 'lfc_queue_ahead', {'phase': 'placement', 'order_id': 'o1', 'leg': 0,
                      'token_id': 'yes1', 'price': '.49', 'own_size': '10', 'visible_at_price': '20',
                      'snapshot_observed_at_utc': at(0), 'lfc_journal_schema': 'lfc_journal_v0.1'}),
                  (6, 'terminal', {'cleanup_ok': True, 'evidence_complete': True, 'unknown_submit': False,
                      'inventory_proven': True, 'post_count': 1, 'order_ids': ['o1']})]
    previous, out = None, []
    for sequence, (seconds, event, fields) in enumerate(events):
        row = {'schema_version': PIN_JOURNAL_VERSION, 'kind': 'journal', 'sequence': sequence,
               'previous_sha256': previous, 'recorded_at_utc': at(seconds), 'event': event, **fields}
        raw = canonical(row)
        previous = hashlib.sha256(raw).hexdigest()
        out.append(raw)
    return b''.join(out)


def receipts(raw):
    # Independent arithmetic: shares 1/7 for 2 seconds, 1/13 for 1 second,
    # rate 10 per second. Two 5-share maker fills, both at our .49 quote.
    reward = D(20) / 7 + D(10) / 13
    rebate = D(0)  # accrued .0312375 is below the venue's $1 daily payout floor
    scope = {'condition_id': 'c1', 'account_id': 'synthetic-account', 'session_id': 'synthetic-session',
             'reward_day': '2026-10-12'}
    return {'scope': scope, 'journal_pin': '124603578f393827fa1b67bd978f6e3b02048ae9',
            'journal_sha256': hashlib.sha256(raw).hexdigest(),
            'lfc_ledger': {'schema_version': 'lfc_l_ledger_v0.1', 'kind': 'lfc_l_ledger',
                           'history_file': 'ledger.jsonl', 'history_rows': 7, 'history_last_sha256': 'a' * 64,
                           'recorded_at_utc': at(6), 'budget_pusd': '100', 'L': '4.9', 'L_filled': '4.9',
                           'L_resting': '0', 'halted': False, 'mismatches': 0, 'stop_reason': None,
                           'our_order_ids': ['o1'], 'legs': [{'session_id': scope['session_id'],
                               'intent_key': 'synthetic-session:1', 'order_id': 'o1', 'token_id': 'yes1',
                               'condition_id': 'c1', 'price': '.49', 'size': '10', 'status': 'terminal',
                               'size_matched': '10'}]},
            'clob': {'endpoint': 'https://clob.polymarket.com/data/trades', 'complete': True,
                     'next_cursor': 'LTE=', 'rows': [
                         {'id': key, 'market': 'c1', 'status': 'CONFIRMED', 'match_time': at(t),
                          'match_time_precision_seconds': '0', 'asset_id': 'yes1',
                          'maker_orders': [{'order_id': 'o1', 'asset_id': 'yes1', 'side': 'BUY',
                                            'maker_address': scope['account_id'],
                                            'price': '.49', 'matched_amount': '5'}]}
                         for key, t in [('actual1', 4), ('actual2', 5)]]},
            'wallet': {'account_id': scope['account_id'], 'session_id': scope['session_id'], 'complete': True,
                       'settlement_complete': True, 'settlement_value': '10',
                       'settlement_source_sha256': 'c' * 64,
                       'start_as_of_utc': at(0), 'as_of_utc': '2026-10-14T10:00:00+00:00',
                       'unattributed_cashflows': [], 'other_attributed_cashflows': [], 'fills': [
                           {'order_id': 'o1', 'price': '.49', 'size': '10'}],
                       'start_cash': '100', 'end_cash': str(D('105.1') + reward + rebate),
                       'reward_credit': str(reward), 'rebate_credit': str(rebate), 'redemption_credit': '10'},
            'rewards': [{**scope, 'as_of_utc': f'2026-10-{day}T10:00:00+00:00',
                         'complete': True, 'session_exclusive': True, 'source_sha256': str(day % 10) * 64,
                         'paid_reward': str(reward)} for day in (13, 14)]}


def tolerance(**changes):
    return Tolerance(**{**dict(reward_absolute='.000001', reward_relative='0', fill_absolute_shares='0',
                              fill_relative='0', markout_absolute_per_share='.000001',
                              receipt_reconciliation_absolute='.000001', min_filled_orders=1,
                              min_paid_reward='.001'), **changes})
