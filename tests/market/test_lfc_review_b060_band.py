"""Guards: B060 refill keeps the real F2Band and shared intent admission gates.

Only closed rehearsal adapters and generated native receipt fixtures are used.
"""
from decimal import Decimal
import pytest

from tests.market.test_lfc_f2_breadth import cities
from tests.market.test_lfc_f2_controller import setup
from tests.market.test_lfc_f2_review_capital import close_fixture
from tests.market.test_lfc_f2_capital import filled
from tests.market.test_lfc_review_b060_refill import BASES, guard, settled_pair
from weather.market.lfc_capital import CapitalBook
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_f2_selection import build_table
from weather.market.mm_stage2_hold import HoldEnd


@pytest.mark.parametrize('basis', BASES)
def test_twelve_stale_band_plans_cannot_double_spend_refilled_headroom(tmp_path, monkeypatch, basis):
    ledger, state, *_ = settled_pair(tmp_path, basis)
    claim = state.claims()[0]
    row = state.read(state.root / 'policies' / (claim['attempt_id'] + '.json'))['policy']
    controller, account, _, ledger, _ = setup(tmp_path, k=12, policy_row=row,
        universe_rows=cities(), shared_ledger=ledger, session_id='after-redemption')
    for n in range(24):
        filled(ledger, 'carried-' + str(n), price='.5', token=str(3000+n), condition='carried',
               market_id=row['market_ids'][n % 12])
    placed = []
    try:
        for band in controller.bands:
            monkeypatch.setattr(band, 'control', lambda **kw: None)
            try:
                for leg in band.TRADE_LEGS:
                    band.submit(leg, band.prices[leg])
            except HoldEnd as exc:
                assert exc.reason in {'capital_total_ceiling', 'per_band_daily_filled_cap'}
                assert band.posts == 0
            else:
                placed.append(band)
            values = CapitalBook(ledger).figures()
            assert values['unrecovered_inventory_cost_native'] + values['resting_reserve_native'] <= 300_000_000
        assert len(placed) == (3 if basis != 'gross' else 2)
        for band in placed:
            from weather.market.lfc_f2_breadth import band_day_usage
            usage = band_day_usage(ledger, band.scope['market_id'], ledger.clock().date().isoformat())
            assert usage['filled_native'] + usage['resting_native'] <= 40_000_000
            assert sum(Decimal(leg['price']) * Decimal(leg['size']) for leg in ledger.legs.values()
                       if leg['session_id'] == band.session_id) <= Decimal('19.60')
        assert all(Decimal(request['price']) * Decimal(request['size']) <= Decimal('15.80')
                   for raw in account.raws for request in raw.calls)
        assert not ledger.unacknowledged_intents()
    finally:
        close_fixture(controller)


@pytest.mark.parametrize('basis', BASES)
def test_selection_uses_the_same_refilled_spendable_cash_as_the_intent_gate(tmp_path, basis):
    ledger, state, *_ = settled_pair(tmp_path, basis)
    claim = state.claims()[0]
    policy = parse_policy(state.read(state.root / 'policies' / (claim['attempt_id'] + '.json'))['policy'])
    for n in range(28):
        filled(ledger, 'carried-' + str(n), price='.5', token=str(3000+n), condition='carried')
    book = CapitalBook(ledger)
    table = build_table(cities(), now=ledger.clock(), policy=policy,
        cash=str(Decimal(book.expected_cash()) / 1_000_000), capital=book.figures())
    assert len(table['selected_condition_ids']) == (1 if basis != 'gross' else 0)
