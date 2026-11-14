"""Guards: T114 fixed W offset, explicit city partitions and disabled successor."""
from copy import deepcopy
import pytest

from tests.market.lfc_pinb_fixtures import pinb_row
from weather.market.lfc_campaign_policy import PolicyRefused
from weather.market.lfc_wide_policy import (
    FIELDS, apply_arm, assignment, disabled_successor, economic_keys, economic_value,
    economic_values, field_keys, validate,
)


def wide_row():
    row = pinb_row()
    row.update(enabled=False, policy_revision=6, post_fill_mode='complete_pairs')
    return disabled_successor(row)


def split_row():
    row = wide_row()
    cities = row['market_ids']
    row['city_quote_offset_assignments'] = [dict(date='2026-11-20', standard_cities=cities[:6], wide_cities=cities[6:])]
    return row


def test_successor_changes_only_revisions_and_two_new_terms():
    original = pinb_row()
    original.update(enabled=False, policy_revision=6, post_fill_mode='complete_pairs')
    frozen = deepcopy(original)
    result = disabled_successor(original)
    assert original == frozen
    assert {key for key in original.keys() | result.keys() if original.get(key) != result.get(key)} == {
        'revision', 'policy_revision', 'quote_offset_mode', 'wide_offset_cents'}
    assert result['policy_revision'] == 7 and result['enabled'] is False
    assert result['post_fill_mode'] == 'complete_pairs'


@pytest.mark.parametrize('value', ['2.5', '3.5', '4.0', None, True, 'NaN', 'Infinity', [], {}])
def test_only_exact_three_cents_is_supported(value):
    row = wide_row(); row['wide_offset_cents'] = value
    with pytest.raises(PolicyRefused, match='unsupported_wide_offset_cents'):
        validate(row)


@pytest.mark.parametrize('value', [3, 3.0, '3.0'])
def test_three_cents_numeric_value(value):
    row = wide_row(); row['wide_offset_cents'] = value
    validate(row)


def test_standard_defaults_and_explicit_standard_have_same_economics():
    assert economic_values({}) == economic_values(dict(quote_offset_mode='standard', wide_offset_cents='3.0'))


def test_frozen_city_partition_is_exact_and_date_specific():
    row = split_row(); validate(row)
    for city in row['market_ids']:
        assert assignment(row, '2026-11-20', city)['quote_offset_mode'] == (
            'standard' if city in row['market_ids'][:6] else 'wide')
        assert assignment(row, '2026-11-19', city)['quote_offset_mode'] == 'wide'


@pytest.mark.parametrize('mutation', ['overlap', 'missing', 'unknown', 'duplicate', 'date', 'revision', 'mode'])
def test_bad_split_or_identity_refuses(mutation):
    row = split_row(); item = row['city_quote_offset_assignments'][0]
    if mutation == 'overlap': item['wide_cities'].insert(0, item['standard_cities'][0])
    if mutation == 'missing': item['standard_cities'].pop()
    if mutation == 'unknown': item['standard_cities'][0] = 'absent'
    if mutation == 'duplicate': row['city_quote_offset_assignments'].append(deepcopy(item))
    if mutation == 'date': item['date'] = '2026-11-23'
    if mutation == 'revision': row['policy_revision'] = 6
    if mutation == 'mode': row['quote_offset_mode'] = 'random'
    with pytest.raises(PolicyRefused): validate(row)


def test_successor_refuses_enabled_or_wrong_source_revision():
    row = pinb_row()
    row.update(enabled=True, policy_revision=6)
    with pytest.raises(PolicyRefused): disabled_successor(row)
    row.update(enabled=False, policy_revision=5)
    with pytest.raises(PolicyRefused): disabled_successor(row)


def test_exact_a092_crossover_keeps_all_original_date_city_arms():
    from weather.market.lfc_campaign_policy import parse_policy
    from weather.market.lfc_f2_breadth import arm
    baseline = parse_policy(pinb_row())
    row = wide_row(); row['quote_offset_mode'] = 'standard'
    friday_wide = ['dallas', 'houston', 'los-angeles', 'miami', 'nyc', 'toronto']
    saturday_wide = ['atlanta', 'austin', 'chicago', 'denver', 'san-francisco', 'seattle']
    row['city_quote_offset_assignments'] = [dict(date=day, wide_cities=wide,
        standard_cities=sorted(set(row['market_ids'])-set(wide))) for day, wide in
        [('2026-11-20', friday_wide), ('2026-11-21', saturday_wide)]]
    validate(row)
    expected_arms = {
        '2026-11-20': ['paired', 'paired', 'cheap', 'paired', 'paired', 'paired',
                       'paired', 'cheap', 'paired', 'cheap', 'paired', 'cheap'],
        '2026-11-21': ['paired', 'paired', 'cheap', 'cheap', 'paired', 'cheap',
                       'cheap', 'paired', 'paired', 'cheap', 'paired', 'cheap']}
    frozen = deepcopy(row)
    for day in expected_arms:
        for city, leg_arm in zip(row['market_ids'], expected_arms[day]):
            original = arm(baseline, day, city)
            result = apply_arm(row, day, city, original)
            assert result['leg_arm'] == leg_arm == original['leg_arm']
            assert result['quote_arm'] == original['quote_arm']
            assert result['standard_quote_offset_pusd'] == original['quote_offset_pusd']
            is_wide = city in (friday_wide if day == '2026-11-20' else saturday_wide)
            assert result['quote_offset_pusd'] == ('0.030' if is_wide else original['quote_offset_pusd'])
            assert result['quote_offset_mode'] == ('wide' if is_wide else 'standard')
    assert row == frozen


def test_economic_identity_includes_exact_partition_and_canonical_offset():
    row = split_row()
    original = economic_values(row)
    row['wide_offset_cents'] = 3
    assert economic_values(row) == original
    item = row['city_quote_offset_assignments'][0]
    item['standard_cities'], item['wide_cities'] = item['wide_cities'], item['standard_cities']
    validate(row)
    assert economic_values(row) != original


def test_old_snapshot_keys_and_economic_defaults_remain_unchanged():
    original = pinb_row()
    keys = {'policy_revision', 'quote_offset_pusd'}
    explicit = original | {'quote_offset_mode': 'standard', 'wide_offset_cents': '3.0'}
    assert field_keys(original, keys) == keys
    assert field_keys(explicit, keys) == keys | {'quote_offset_mode', 'wide_offset_cents'}
    assert economic_keys(original, keys | FIELDS) == economic_keys(explicit, keys | FIELDS) == keys
    for key in FIELDS:
        assert economic_value(original, key) == economic_value(explicit, key)
    assert economic_keys(wide_row(), keys) == keys | FIELDS
    with pytest.raises(PolicyRefused, match='wide_requires_pinb'):
        validate(wide_row() | {'schema_version': 'lfc_campaign_policy_v0.3'})
