"""Guards: T113 exact economic mode, disabled revision-6 successor and hash defaults."""
from copy import deepcopy

import pytest

from tests.market.lfc_pinb_fixtures import pinb_row
from weather.market.lfc_campaign_policy import PolicyRefused, parse_policy
from weather.market.lfc_pair_policy import (
    economic_keys, economic_value, field_keys, successor_row, validate,
)


def test_successor_changes_only_explicit_approved_policy_fields():
    old = parse_policy(pinb_row())
    before = deepcopy(old.raw)
    row = successor_row(old)
    changed = {key for key in set(row) | set(before) if row.get(key) != before.get(key)}
    assert changed == {'revision', 'policy_revision', 'post_fill_mode'}
    assert row['policy_revision'] == 6 and row['post_fill_mode'] == 'complete_pairs'
    assert row['enabled'] is False and old.raw == before


def test_enabled_source_still_prepares_only_a_disabled_successor():
    old = pinb_row() | {'enabled': True}
    row = successor_row(parse_policy(old))
    assert row['enabled'] is False and old['enabled'] is True


@pytest.mark.parametrize('value', [None, True, 1, [], 'complete', 'COMPLETE_PAIRS', 'continue '])
def test_policy_accepts_only_the_two_exact_mode_strings(value):
    with pytest.raises(PolicyRefused, match='unsupported_post_fill_mode'):
        validate(pinb_row() | {'post_fill_mode': value})


@pytest.mark.parametrize('revision', [5, 0, True])
def test_complete_pairs_requires_new_economic_revision(revision):
    with pytest.raises(PolicyRefused, match='complete_pairs_requires_policy_revision_6'):
        validate(pinb_row() | {'post_fill_mode': 'complete_pairs', 'policy_revision': revision})


def test_complete_pairs_requires_pinb_and_existing_fill_continuation():
    row = pinb_row() | {'policy_revision': 6, 'post_fill_mode': 'complete_pairs'}
    assert validate(row) == 'complete_pairs'
    with pytest.raises(PolicyRefused, match='complete_pairs_requires_pinb'):
        validate(row | {'schema_version': 'lfc_campaign_policy_v0.3'})
    with pytest.raises(PolicyRefused, match='complete_pairs_requires_fill_continuation'):
        validate(row | {'on_first_band_fill': 'cancel_remaining_orders_in_band_and_retire_band'})


def test_historical_default_preserves_bytes_keys_and_economic_identity():
    old = pinb_row()
    keys = {'quote_offset_pusd', 'policy_revision'}
    assert validate(old) == 'continue' and 'post_fill_mode' not in old
    assert field_keys(old, keys) == keys
    explicit = old | {'post_fill_mode': 'continue'}
    assert field_keys(explicit, keys) == keys | {'post_fill_mode'}
    assert economic_keys(old, keys) == economic_keys(explicit, keys | {'post_fill_mode'}) == keys
    assert economic_value(old, 'post_fill_mode') == economic_value(explicit, 'post_fill_mode') == 'continue'
    assert economic_keys(old | {'post_fill_mode': 'complete_pairs'}, keys) == keys | {'post_fill_mode'}
