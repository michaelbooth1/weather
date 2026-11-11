"""Guards: B085 U6/U7 future campaign tokens cannot rewrite historical anchors."""
from datetime import timedelta

import pytest

from tests.market.test_lfc_f2_overlap_b082 import wallet, feed
from tests.market.test_lfc_f2_inventory_b080 import observation
from weather.market.lfc_capital import CapitalBook
from weather.market.lfc_capital_reads import synchronize
from weather.market.lfc_ledger import Ledger
from weather.market.mm_stage2_hold import digest


def later_intent(ledger, token):
    ledger.record('session_start', session_id='later', counted=True)
    ledger.intent(session_id='later', intent_key='later:1', token_id=token, condition_id='later-condition',
                  size='20', price='.4', fee_rate_bps='0')


@pytest.mark.parametrize('warm', [False, True])
def test_personal_token_change_before_future_campaign_intent_replays(tmp_path, warm):
    ledger, _, clock, _, _, _, _ = wallet(tmp_path, campaign=False)
    first = CapitalBook(ledger).inventory_anchor
    synchronize(ledger, first, observation(ledger, clock, positions=first['positions'], cash='290'), anchor_mode='session')
    clock.value += timedelta(days=1)
    positions = {**first['positions'], '999': '50'}
    synchronize(ledger, CapitalBook(ledger).inventory_anchor,
                observation(ledger, clock, positions=positions, cash='265'), anchor_mode='session')
    assert CapitalBook(ledger).inventory_anchor['positions']['999'] == '50'
    clock.value += timedelta(days=1)
    later_intent(ledger, '999')
    expected = CapitalBook(ledger).figures()
    if warm:
        ledger._replay()
    else:
        ledger = Ledger.open(ledger.path, clock=clock.now)
    assert CapitalBook(ledger).figures() == expected
    assert ledger.unacknowledged_intents()[0]['intent_key'] == 'later:1'


@pytest.mark.parametrize('warm', [False, True])
def test_pre_anchor_personal_redemption_keeps_funding_when_token_traded_later(tmp_path, warm):
    from tests.market.test_lfc_f2_capital import filled
    ledger, baseline, clock, source, receipt, tokens, campaign = wallet(tmp_path, campaign=False, enroll=False)
    # The losing leg is campaign-owned; the winning leg is personal. This
    # condition-scoped receipt is therefore fetched by the real native rail.
    clock.value -= timedelta(seconds=60)
    filled(ledger, 'campaign-loser', token=tokens[1], condition=source['condition_id'])
    clock.value += timedelta(seconds=60)
    source['timestamp'] = int(clock.now().timestamp()) - 20
    receipt.update(rows=[source], rows_sha256=digest([source]))
    synchronize(ledger, baseline, observation(ledger, clock, positions={campaign: '20', tokens[1]: '20'}, cash='282'),
                anchor_mode='enrollment')
    clock.value += timedelta(seconds=90)
    read = feed(ledger, clock, source, receipt, {campaign: '20'}, '282')
    assert synchronize(ledger, CapitalBook(ledger).inventory_anchor, read)['cash_bridge_complete']
    assert len(CapitalBook(ledger).activities) == 1
    assert next(iter(CapitalBook(ledger).activities.values()))['cash_native'] == 20_000_000
    assert CapitalBook(ledger).figures()['funding_native'] == 300_000_000
    clock.value += timedelta(days=1)
    later_intent(ledger, tokens[0])
    expected = CapitalBook(ledger).figures()
    if warm:
        ledger._replay()
    else:
        ledger = Ledger.open(ledger.path, clock=clock.now)
    assert CapitalBook(ledger).figures()['funding_native'] == 300_000_000
    assert CapitalBook(ledger).figures() == expected
