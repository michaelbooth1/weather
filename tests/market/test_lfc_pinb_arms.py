"""Guards: B072 deterministic independent leg/distance arms and actual intents."""
from copy import deepcopy
from decimal import Decimal
import pytest

from tests.market.lfc_pinb_fixtures import pinb_row
from tests.market.test_lfc_f2_controller import setup, MAKER
from tests.market.test_lfc_campaign import Mutexes
from tests.market.test_lfc_f2_breadth import cities, NOW
from tests.market.test_lfc_f2_selection import capital
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_f2_breadth import arm, captured_market_ids
from weather.market.lfc_f2_selection import build_table, validate_table
from weather.market.lfc_campaign_proof import local_money_proof
from weather.market.lfc_recording_io import strict_json


def test_pinb_leg_arm_is_deterministic_and_learning_only():
    policy = parse_policy(pinb_row())
    assignments = [arm(policy, '2026-11-12', market) for market in captured_market_ids()]
    assert {a['leg_arm'] for a in assignments} == {'paired', 'cheap'}
    for market, selected in zip(captured_market_ids(), assignments):
        assert arm(policy, '2026-11-12', market) == selected
        fixed = arm(policy, '2026-11-23', market)
        assert fixed['leg_arm'] == 'paired' and fixed['leg_arm_assignment'] == 'fixed-paired'
        assert fixed['quote_offset_pusd'] == '0.015'
    revised = {**policy.raw, 'policy_revision': 6}
    assert arm(parse_policy(revised), '2026-11-12', captured_market_ids()[0]) == assignments[0]


def test_cheap_arm_selects_one_leg_and_reserves_only_its_cost():
    paired = pinb_row(); paired['learning_leg_arms'] = ['paired']
    cheap = {**paired, 'learning_leg_arms': ['cheap']}
    paired_policy, cheap_policy = parse_policy(paired), parse_policy(cheap)
    full = build_table(cities(), now=NOW, policy=paired_policy, cash='300', capital=capital())
    single = build_table(cities(), now=NOW, policy=cheap_policy, cash='300', capital=capital())
    originals = {r['condition_id']: r for r in full['rows']}
    selected = validate_table(single, now=NOW, policy=cheap_policy)
    assert len(selected) == 12
    for row in selected:
        assert row['leg_arm'] == 'cheap' and len(row['trade_legs']) == 1
        quote = row['quote']; prices = [Decimal(quote['yes_buy']), Decimal(quote['no_buy'])]
        assert prices[row['trade_legs'][0]] == min(prices)
        assert Decimal(quote['reserve_pusd']) == Decimal('20')*min(prices)
        assert Decimal(quote['reserve_pusd']) < Decimal(originals[row['condition_id']]['quote']['reserve_pusd'])


def test_arm_reaches_plan_journal_ledger_intent_and_complete_outcome(tmp_path):
    with account_lease(MAKER, backend=Mutexes()):
        row = pinb_row(); row['learning_leg_arms'] = ['cheap']
        controller, account, status, ledger, clock = setup(tmp_path, policy_row=row)
        result = controller.run()
        assert result['cleanup_ok'] and result['post_count'] == 2
        intents = ledger.event_rows('leg_intent')
        assert len(intents) == 2 and {r['leg_arm'] for r in intents} == {'cheap'}
        for band in controller.bands:
            prediction = strict_json((band.directory/'prediction.json').read_bytes())
            assert prediction['scope']['leg_arm_assignment'] == 'learning-cheap'
            assert len(prediction['scope']['trade_legs']) == 1
        outcome = status.finish(success=True)
        assert {b['leg_arm'] for b in outcome['bands']} == {'cheap'}
        proof = local_money_proof(controller.directory, ledger=ledger, session_id=controller.session_id,
                                 attempt_id='a'*32, outcome=outcome)
        assert proof['complete'] and not proof['unknown_submit']
