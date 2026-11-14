"""Guards: T114 exact city crossover selection, reproducibility and order evidence."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal

import pytest

from tests.market.lfc_wide_fixtures import controller_fixture, policy_row
from tests.market.test_lfc_f2_breadth import cities
from tests.market.test_lfc_f2_selection import capital
from tests.market.test_lfc_pair_integration import journal
from tests.market.test_lfc_wide_successor import crossover
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_f2_breadth import arm
from weather.market.lfc_f2_selection import build_table, validate_table
from weather.market.lfc_wide_policy import successor_row


@pytest.mark.parametrize('day', ['2026-11-20', '2026-11-21'])
def test_exact_two_date_split_prices_all_cities_without_changing_arm_hashes(day):
    baseline = parse_policy(policy_row('complete_pairs'))
    assignments = crossover(baseline.raw['market_ids'])
    policy = parse_policy(successor_row(baseline, post_fill_mode='complete_pairs', quote_offset_mode='standard',
                                       city_assignments=assignments))
    now = datetime.fromisoformat(day+'T14:00:00+00:00')
    table = build_table(cities(now=now), now=now, policy=policy, cash='300', capital=capital())
    assert len(validate_table(table, now=now, policy=policy)) == 12
    for row in table['rows']:
        wide = row['market_id'] in next(r for r in assignments if r['date'] == day)['wide_cities']
        original = arm(baseline, day, row['market_id'])
        assert row['leg_arm'] == original['leg_arm'] and row['quote_arm'] == original['quote_arm']
        assert row['quote_offset_mode'] == ('wide' if wide else 'standard')
        assert row['quote_offset_pusd'] == ('0.030' if wide else original['quote_offset_pusd'])
        assert row['offset_assignment_source'] == 'city_quote_offset_assignments'
        if wide:
            assert Decimal(row['quote']['yes_buy']) == Decimal('.31')
    altered = deepcopy(table)
    altered['rows'][0]['quote_offset_mode'] = 'wide' if altered['rows'][0]['quote_offset_mode'] == 'standard' else 'standard'
    with pytest.raises(ValueError, match='f2_selection_not_reproducible'):
        validate_table(altered, now=now, policy=policy)


def test_actual_narrow_and_wide_city_orders_record_their_frozen_assignment(tmp_path):
    source = policy_row('complete_pairs', market_ids=['atlanta', 'dallas'])
    row = successor_row(source, post_fill_mode='complete_pairs', quote_offset_mode='standard',
        city_assignments=[dict(date='2026-11-11', standard_cities=['atlanta'], wide_cities=['dallas'])])
    controller, account, _, ledger, *_ = controller_fixture(tmp_path, row, seconds=300)
    account.fills_enabled = False
    result = controller.run()
    assert result['cleanup_ok'] and not ledger.unresolved_legs(), result
    for band in controller.bands:
        wide = band.scope['market_id'] == 'dallas'
        scores = [r for r in journal(band) if r['event'] == 'quote_scoring_order']
        assert scores and all(r['quote_offset_mode'] == ('wide' if wide else 'standard') and
                             r['offset_assignment_source'] == 'city_quote_offset_assignments' for r in scores)
        assert band.OFFSET == (Decimal('.030') if wide else Decimal(band.scope['standard_quote_offset_pusd']))
