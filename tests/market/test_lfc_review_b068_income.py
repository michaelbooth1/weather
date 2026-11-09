"""Guards: B068 payment labels never prove the complete earning-order history."""
from copy import deepcopy
import pytest
from tests.market.test_lfc_campaign import MAKER, Mutexes
from tests.market.test_lfc_review_b060_refill import settled_pair
from tests.market.test_lfc_review_b066_incoming import incoming, resolve
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_capital import CapitalBook, CapitalRefused
from weather.market.lfc_ledger import Ledger


@pytest.fixture(autouse=True)
def guarded():
    with account_lease(MAKER, backend=Mutexes()): yield


@pytest.mark.parametrize('kind', ['REWARD', 'MAKER_REBATE'])
@pytest.mark.parametrize('history', ['missing', 'owner_order', 'campaign_only_assertion'])
@pytest.mark.parametrize('basis', ['gross', 'net_of_retained_gains'])
def test_native_payment_needs_proved_period_and_complete_own_order_history(tmp_path, kind, history, basis):
    ledger, *_ = settled_pair(tmp_path, basis)
    before = CapitalBook(ledger).figures()
    source, proof = incoming(ledger, kind=kind, campaign=True, missing=True)
    if history != 'missing':
        # Unsupported, unbound claims must not smuggle attribution through the
        # native cash packet. No API endpoint/field is invented for this input.
        proof = deepcopy(proof)
        proof['order_history'] = {'complete': True, 'campaign_only': history == 'campaign_only_assertion'}
    resolve(ledger, source, proof)
    for view in (ledger, Ledger.open(ledger.path, clock=ledger.clock)):
        book = CapitalBook(view); row = book.figures()
        assert row['proven_campaign_profit_cumulative_native'] == before['proven_campaign_profit_cumulative_native']
        assert row['retained_gains_available_native'] == before['retained_gains_available_native']
        assert row['unknown_cash_held_native'] == 5_000_000 and row['unknown_payouts']
        assert 'reward_attribution_unproven' in row['retained_gains_reason_codes']
        assert row['headroom_native'] <= 300_000_000
        assert row['unrecovered_inventory_cost_native']+row['resting_reserve_native'] <= 300_000_000
        with pytest.raises(CapitalRefused, match='capital_total_ceiling'):
            book.gate(reserve='300.000001', available_cash='2000')


@pytest.mark.parametrize('basis', ['gross', 'net_of_retained_gains'])
def test_unknown_reward_attribution_never_turns_owner_cash_into_gains(tmp_path, basis):
    ledger, *_ = settled_pair(tmp_path, basis, winner=False)
    incoming(ledger, kind='MAKER_REBATE', campaign=True, missing=False)
    incoming(ledger, kind='DEPOSIT', amount='200', missing=False, nonce=73)
    for view in (ledger, Ledger.open(ledger.path, clock=ledger.clock)):
        row = CapitalBook(view).figures()
        assert row['retained_gains_available_native'] == row['proven_campaign_profit_cumulative_native'] == 0
        assert row['headroom_native'] == 290_400_000
