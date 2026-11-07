"""Planning cannot become income, including late native settlement evidence.

Guards: B036 honest fees, carry, principal, incentives and one final cash look.
"""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_f2_capital import activity, filled, install, ledger_at
from tests.market.test_lfc_f2_controller import setup
from weather.market.lfc_capital import record_activity
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_f2_economics import economics, measured, final_cash_assessment
from weather.market.lfc_f2_policy import example_policy


def test_prediction_never_books_income_and_unknown_fee_is_not_zero(tmp_path):
    controller, account, status, ledger, clock = setup(tmp_path)
    account.filled_band, account.fill_at = 0, 12
    controller.run()
    row = status.finish(success=True)['economics']
    assert row['planning']['predicted_360_minute_reward'] > 0
    assert row['planning']['booked_as_income'] is False
    assert row['measured']['fees']['maker_fee_paid_native'] is None
    assert row['measured']['rewards']['actually_paid_native'] is None
    assert row['measured']['rewards']['accruals'] == []
    assert row['measured']['fills'][0]['purchase_cost_native'] > 0
    assert row['measured']['carried_inventory']


def test_measured_redemption_changes_carry_without_changing_planning(tmp_path):
    ledger = ledger_at(tmp_path)
    filled(ledger, 'lot')
    install(ledger)
    first = measured(ledger, ['lot'])
    assert first['carried_inventory'][0]['cost_basis_native'] == 10_000_000
    record_activity(ledger, activity(cash='20'))
    second = measured(ledger, ['lot'])
    assert second['carried_inventory'] == []
    redeemed = second['settlement']['redemptions'][0]
    assert redeemed['cash_native'] == redeemed['session_cash_native'] == 20_000_000
    assert redeemed['returned_principal_native'] == 10_000_000
    assert second['campaign_capital']['segregated_profit_native'] == 10_000_000


def test_unknown_settlement_and_observed_account_reward_never_invent_session_income(tmp_path):
    ledger = ledger_at(tmp_path)
    filled(ledger, 'lot')
    install(ledger)
    record_activity(ledger, activity(cash=None))
    record_activity(ledger, activity(cash='7', size='0', kind='REWARD', tx='reward'))
    row = measured(ledger, ['lot'])
    assert row['settlement']['redemptions'][0]['session_cash_native'] is None
    assert row['settlement']['unknown_payouts']
    rewards = row['rewards']
    assert rewards['account_cash_credits'][0]['cash_native'] == 7_000_000
    assert rewards['actually_paid_native'] is None and not rewards['earned_session_link_verified']


def test_joint_redemption_never_assigns_whole_payment_to_each_session(tmp_path):
    ledger = ledger_at(tmp_path)
    filled(ledger, 'first', size='10')
    filled(ledger, 'second', size='10')
    install(ledger)
    record_activity(ledger, activity(cash='20'))
    for sid in ('first', 'second'):
        redemption = measured(ledger, [sid])['settlement']['redemptions'][0]
        assert redemption['cash_native'] == 20_000_000
        assert redemption['session_cash_native'] is None and not redemption['exclusive_session_scope']


def test_positive_cash_is_separate_from_expected_profit_qualification():
    policy = parse_policy(example_policy())
    now = datetime(2026, 12, 28, 23, tzinfo=timezone.utc)
    result = final_cash_assessment(policy, profit_native=1, complete=True, family_closed=True, now=now)
    assert result['cash_positive'] and result['state'] == 'INCONCLUSIVE'
    assert result['lower_confidence_bound_native'] == '-284999999.95'
    assert result['independent_campaigns'] == 1 and result['nominal_dates'] == 36
    assert final_cash_assessment(policy, profit_native=None, complete=False, family_closed=True, now=now)['net_cash_native'] is None
    with pytest.raises(ValueError, match='success_look_not_open'):
        final_cash_assessment(policy, profit_native=1, complete=True, family_closed=True,
                              now=now.replace(hour=22))
