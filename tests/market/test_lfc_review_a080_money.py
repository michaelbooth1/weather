"""Guards: replacing spent campaign gains with personal sale proceeds is no refill."""
from datetime import timedelta
from types import SimpleNamespace
import pytest

from tests.market.test_lfc_f2_inventory_b080 import fixture, observation
from tests.market.test_lfc_f2_capital import filled
from tests.market.test_lfc_redemption_native import paired
from weather.market.lfc_capital import CapitalBook, CapitalRefused, record_activity
from weather.market.lfc_capital_reads import synchronize
from weather.market.lfc_ledger import Ledger
from weather.market.lfc_campaign_runtime import Runtime
from weather.market.lfc_f2_pinb import example_policy
from weather.market.lfc_recording_io import write_new
from weather.market.mm_stage2_hold import digest


@pytest.mark.parametrize('reopen', [False, True])
def test_personal_buy_then_sale_cannot_preserve_spent_campaign_gains(tmp_path, reopen):
    ledger, baseline, clock, _ = fixture(tmp_path, personal=False, bridge=False)
    source, proof, tokens = paired(auto=True)
    for index, token in enumerate(tokens):
        filled(ledger, f'pair-{index}', token=token, condition=source['condition_id'], price='.48')
    read = observation(ledger, clock, positions={'denver': '20', 'owner-old-nfl': '20', **{t: '20' for t in tokens}}, cash='270.8')
    synchronize(ledger, baseline, read, anchor_mode='enrollment', loss_basis='net_of_retained_gains')
    clock.value += timedelta(minutes=1)
    source['timestamp'] = int(clock.now().timestamp())
    proof.update(rows=[source], rows_sha256=digest([source]))
    record_activity(ledger, source, native_evidence=proof)
    before = CapitalBook(ledger)
    assert before.figures(loss_basis='net_of_retained_gains')['retained_gains_available_native'] == 10_400_000
    # Allowed outside-session personal trades: spend the 10.4 profit on a new
    # NFL holding, then sell a previously owned NFL holding for the same cash.
    # Activity excludes TRADE; the complete SDK trade list retains both fills.
    clock.value += timedelta(hours=1)
    after = observation(ledger, clock, positions={'denver': '20', 'owner-new-nfl': '20'}, cash='290.8')
    for seconds, side, token in [(2, 'BUY', 'owner-new-nfl'), (1, 'SELL', 'owner-old-nfl')]:
        after['trades'].append({'id': 'owner-'+side, 'trader_side': 'TAKER', 'status': 'CONFIRMED',
            'matched_at': (clock.now()-timedelta(seconds=seconds)).isoformat(),
            'taker_order_id': 'owner-'+side, 'token_id': token, 'side': side, 'size': '20', 'price': '.52', 'fee_rate_bps': '0'})
    path = tmp_path/'campaign.json'; write_new(path, example_policy())
    runtime = object.__new__(Runtime)
    runtime.clock, runtime.policy_path, runtime.preparing_f2 = clock, path, True
    runtime.state = SimpleNamespace(ledger=ledger, maker=after['maker_address'], root=tmp_path/'state')
    result = runtime.core_proof(ledger, after, loss_basis='net_of_retained_gains')
    assert result['money_accounting_complete'] and result['capital']['cash_bridge_complete']
    if reopen:
        ledger = Ledger.open(ledger.path, clock=clock.now)
    book = CapitalBook(ledger)
    figures = book.figures(loss_basis='net_of_retained_gains')
    # The incorrect surviving offset is usable by the actual capital gate.
    with pytest.raises(CapitalRefused, match='capital_total_ceiling'):
        book.gate(reserve='290', available_cash='290.8', loss_basis='net_of_retained_gains')
    # Reach the boundary using individually valid 10 pUSD fills across later
    # sessions; then one ordinary 19.60 paired reserve demonstrates the leak.
    # This is within I+R=299.60, but correct no-top-up accounting is 309.20:
    # 280 inventory + 19.60 new reserve + 9.60 loss, with the gains spent.
    for index in range(27):
        clock.value += timedelta(days=1)
        book.gate(reserve='10', available_cash=str((290_800_000-index*10_000_000)/1_000_000),
                  loss_basis='net_of_retained_gains')
        filled(ledger, 'later-'+str(index), token='later-'+str(index), condition='later-'+str(index))
        book = CapitalBook(ledger)
    with pytest.raises(CapitalRefused, match='capital_total_ceiling'):
        book.gate(reserve='19.6', available_cash='20.8', loss_basis='net_of_retained_gains')
    assert book.figures(loss_basis='net_of_retained_gains')['unrecovered_inventory_cost_native'] == 280_000_000
    with pytest.raises(CapitalRefused, match='capital_total_ceiling'):
        book.gate(reserve='19.6', available_cash='20.8', loss_basis='gross')
    # Existing B060 rule: every non-campaign outflow consumes gains first.
    assert figures['retained_gains_available_native'] == 0, {
        'retained': figures['retained_gains_available_native'], 'offset': figures['retained_gains_offset_native'],
        'headroom': figures['headroom_native'], 'cash': book.expected_cash(),
        'withdraw_movements': [m for m in book.pool_movements if m['kind'] == 'withdraw']}
