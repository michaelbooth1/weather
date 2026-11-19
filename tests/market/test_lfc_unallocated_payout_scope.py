"""Invented lots and decoded native-burn operands. No venue or retained records."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from weather.market import lfc_f2_economics as economics, lfc_f2_reward_estimate
from weather.market.lfc_capital import CapitalBook
from weather.market.lfc_capital_income import unknown_cash


NOW = datetime(2020, 1, 2, 1, 0, 0, 500000, tzinfo=timezone.utc)
SECOND = int(NOW.timestamp())


def book_with_burn(token='71', when=SECOND + 1):
    history = [dict(event='leg_intent', intent_key='lot', recorded_at_utc=NOW.isoformat()),
               dict(event='leg_terminal', order_id='O', sequence=1)]
    lot = dict(session_id='S', token_id='71', condition_id='selected', order_id='O',
               status='terminal', size_matched='3', price='.4')
    ledger = SimpleNamespace(rows=history, legs={'lot': lot}, baselines=[])
    book = CapitalBook(ledger)
    # One decoded native bundle can cover several contracts under a single activity.
    activity = dict(id='R', type='REDEEM', timestamp=when, condition_id='nominal-other',
                    token_id='nominal-other', cash_native=5_000_000, native_redemption=dict(
                        transaction_hash='invented-tx',
                        positions=[dict(token_id=token, quantity='5', cash_native=5_000_000)]))
    book.activities['R'] = activity
    book.activity_sequences['R'] = 2
    book.activity_transactions['R'] = 'invented-tx'
    book.redeem(activity, 2)
    return ledger, book


def test_normal_report_keeps_possible_burn_and_credit_separate(monkeypatch):
    ledger, book = book_with_burn()
    assert book.allocations == []
    assert book.redemptions['R']['unallocated'][0]['token_id'] == '71'
    assert unknown_cash(book)['blockers'] == ['R']
    assert book.lots['lot']['remaining_basis'] == 1_200_000
    monkeypatch.setattr(economics, 'CapitalBook', lambda _: book)
    monkeypatch.setattr(book, 'figures', lambda: {'blockers': unknown_cash(book)['blockers']})
    monkeypatch.setattr(lfc_f2_reward_estimate, 'summary', lambda *_: {})
    result = economics.measured(ledger, ['S'])
    assert result['settlement']['unknown_payouts'] == ['R']
    assert result['settlement']['possible_unallocated_payouts_by_token'] == {'R': ['71']}
    assert result['settlement']['redemptions'] == result['settlement']['cost_basis_releases'] == []
    assert result['campaign_capital']['blockers'] == ['R']
    unrelated = economics.measured(ledger, ['unrelated'])['settlement']
    assert unrelated['unknown_payouts'] == []
    assert 'possible_unallocated_payouts_by_token' not in unrelated


@pytest.mark.parametrize(('token', 'when', 'sessions', 'expected'), [
    ('71', SECOND, {'S'}, {'R': ['71']}), ('71', SECOND - 1, {'S'}, {}),
    ('99', SECOND + 1, {'S'}, {}), ('71', SECOND + 1, {'another'}, {}),
])
def test_token_membership_and_coarse_clock(token, when, sessions, expected):
    _, book = book_with_burn(token, when)
    assert economics.possible_unallocated_payouts(book, sessions, set()) == expected


def test_existing_allocation_and_unproved_api_rows_gain_no_new_authority():
    _, book = book_with_burn()
    assert economics.possible_unallocated_payouts(book, {'S'}, {'R'}) == {}
    del book.activities['R']['native_redemption']
    assert economics.possible_unallocated_payouts(book, {'S'}, set()) == {}
