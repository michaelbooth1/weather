"""Native redemption accounting with original Astra safety witnesses.

Guards: B040 M1/M2, per-lot principal limits, paired redemption and read races.
All native transfers, API activity and chain envelopes are synthetic fixtures.
"""
from types import SimpleNamespace
import pytest
from tests.market.test_lfc_f2_capital import MAKER, NOW, activity, filled, install, ledger_at
from tests.market.test_lfc_f2_capital_reads import packet, rpc_packet, native_packet, setup_read
from tests.market.test_lfc_f2_native import proof as native_proof, TX
from weather.market.lfc_capital import ASSET, CapitalBook, CapitalRefused, native, record_activity
from weather.market.lfc_capital_reads import read_activity, synchronize
from weather.market.lfc_ledger import Ledger, take_baseline, write_baseline
from weather.market.lfc_recording_io import write_new


def observed_packet(rows, proofs):
    result = read_activity(MAKER, int(NOW.timestamp()), int(NOW.timestamp()),
                           get=lambda *a: packet(rows), sleep=lambda _: None)
    result = native_packet(result)
    result['native_receipts'] = proofs
    return result



def set_cash(read, cash):
    read['balances'] = {'available_collateral': cash, 'assets': {ASSET: cash},
                        'collateral_evidence': {'balance': str(native(cash))}}



@pytest.mark.parametrize('initially_unknown', [False, True])
def test_mixed_basis_lots_must_not_net_one_lots_loss_against_another_profit(tmp_path, initially_unknown):
    ledger = ledger_at(tmp_path)
    baseline = take_baseline(label='t40', now=NOW, maker_address=MAKER, positions=[],
                             open_orders=[], available_collateral='300')
    write_baseline(ledger.path.parent, baseline, ledger)
    filled(ledger, 'high-basis', price='.70')
    filled(ledger, 'low-basis', price='.30')
    read = {'complete': True, 'maker_address': MAKER, 'open_orders': [],
            'positions': [{'asset':'yes', 'size':'40'}], 'ended_at_utc': NOW.isoformat(),
            'capital_activity': observed_packet([], {})}
    set_cash(read, '280')
    assert synchronize(ledger, baseline, read)['headroom_native'] == 280_000_000
    source = activity(cash='20', size='40', tx=TX)
    proof = native_proof([source], incoming=20_000_000)
    if initially_unknown:
        unknown = {**proof, 'receipt': rpc_packet(None)}
        read['capital_activity'] = observed_packet([source], {TX: unknown})
        read['positions'] = []
        set_cash(read, '300')
        unknown_facts = synchronize(ledger, baseline, read)
        assert unknown_facts['returned_principal_native'] == 0
    read['capital_activity'] = observed_packet([source], {TX: proof})
    read['positions'] = []
    set_cash(read, '300')
    try:
        after_redemption = synchronize(ledger, baseline, read)
    except CapitalRefused:
        return  # Refusing an allocation that cannot be proved is safe too.
    # Same-token 0.50/share redemption: high lot loses 4; low lot earns 4.
    # Per-lot principal is min(14,10)+min(6,10)=16, not min(20,20)=20.
    for i in range(29):
        filled(ledger, 'later'+str(i), token='later'+str(i))
    ledger.record('session_start', session_id='last', counted=True)
    book = CapitalBook(ledger)
    assert book.expected_cash() == 10_000_000
    # The existing controller's money gates and lowest durable intent gate
    # must both reject a ten-unit order: true charge would be 290 + 4 + 10.
    try:
        book.gate(reserve='10', available_cash='10')
        ledger.intent(session_id='last', intent_key='last', token_id='last', condition_id='last',
                      price='.50', size='20', fee_rate_bps='0')
    except CapitalRefused:
        return
    trace = {'after_redemption': after_redemption, 'after_admitted_intent': CapitalBook(ledger).figures(),
             'expected_per_lot_principal_native':16_000_000, 'expected_loss_native':4_000_000,
             'expected_segregated_profit_native':4_000_000, 'true_charged_native':304_000_000,
             'initially_unknown': initially_unknown}
    write_new(tmp_path/'witness-evidence.json', trace)
    pytest.fail('M1: cash gate and durable intent admitted 10 pUSD at true charge 304; per-lot loss/profit were netted')



def test_prebridge_unknown_payout_must_not_become_an_owner_contribution(tmp_path):
    ledger, baseline, read = setup_read(tmp_path)
    # Baseline has 100, original fill costs 10, native receipt unavailable.
    # Current wallet is 110 after a 20 payout; no owner contribution occurred.
    source = activity(cash=None, tx=TX)
    read['capital_activity'] = observed_packet([source], {TX: {**native_proof([source]), 'receipt': rpc_packet(None)}})
    read['positions'] = []
    set_cash(read, '110')
    try:
        facts = synchronize(ledger, baseline, read)
    except CapitalRefused:
        return  # Initial bridge may refuse until principal provenance is proved.
    assert facts['returned_principal_native'] == 0 and facts['unknown_payouts']
    from weather.market.lfc_campaign_runtime import Runtime
    from weather.market.lfc_campaign_reads import ACCOUNT_READ_COMPONENTS
    read.update(schema_version='lfc_campaign_account_read_v0.1', errors=[],
                scope='account_wide_sdk_trades_and_f0_v2_positions', since=str(int(NOW.timestamp())),
                started_at_utc=NOW.isoformat(), geography={'blocked':False},
                trades=[{'status':'CONFIRMED', 'maker_orders':[{'order_id':'order-legacy','matched_amount':'20'}]}],
                component_times={name:{'started_at_utc':NOW.isoformat(),'ended_at_utc':NOW.isoformat()}
                                 for name in ACCOUNT_READ_COMPONENTS})
    runtime = SimpleNamespace(state=SimpleNamespace(maker=MAKER), clock=SimpleNamespace(now=lambda:NOW),
                              original_baseline=lambda _: baseline)
    monetary = Runtime.core_proof(runtime, ledger, read)
    # Nine later 20-share fills consume the genuine remaining principal. The
    # next order must not use the still-unproved incoming cash.
    for i in range(9):
        filled(ledger, 'later'+str(i), token='later'+str(i))
    book = CapitalBook(ledger)
    extra_admitted = False
    try:
        book.gate(reserve='10', available_cash='20')
        ledger.record('session_start', session_id='extra', counted=True)
        ledger.intent(session_id='extra', intent_key='extra', token_id='extra', condition_id='extra',
                      price='.5', size='20', fee_rate_bps='0')
        extra_admitted = True
    except CapitalRefused:
        pass
    write_new(tmp_path/'witness-evidence.json', {'initial_bridge': facts, 'core_money_proof':monetary,
              'after_extra_order':CapitalBook(ledger).figures(), 'actual_owner_principal_native':100_000_000,
              'unproved_cash_promoted_to_funding_native':20_000_000, 'extra_order_admitted':extra_admitted})
    assert facts['funding_native'] == 100_000_000, facts
    assert facts['headroom_native'] == 90_000_000, facts
    assert extra_admitted is False
