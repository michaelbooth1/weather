"""Owner approved F2 fields, each with an acceptance and refusal boundary.

Guards: B036 Appendix A, fixed-end late starts and no implicit unsupported terms.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_f2_policy import FIXED, VARIABLE, example_policy


def test_approved_example_has_two_bands_one_event_per_city_and_no_hidden_stops():
    policy = parse_policy(example_policy())
    assert policy.f2 and policy.terms['budget_pusd'] == '300' and policy.terms['k_max'] == 2
    assert policy.raw['events_per_city'] == 1
    assert policy.terms['daily_loss_cap'] is policy.terms['realised_stop'] is policy.terms['per_date_cap'] is None
    assert policy.terms['max_sessions'] is None  # Account/date claims own the finite calendar.
    assert len(policy.entries) == 42
    assert not any(e.local_date in ('2026-11-09', '2026-11-16') for e in policy.entries)
    assert policy.entries[-1].local_date == '2026-12-22'


@pytest.mark.parametrize('field', sorted(FIXED))
def test_each_fixed_field_accepts_approved_and_refuses_unsupported(field):
    row = example_policy()
    assert parse_policy(row).raw[field] == FIXED[field]
    value = row[field]
    row[field] = not value if type(value) is bool else 'unsupported' if isinstance(value, str) else 999
    with pytest.raises(ValueError):
        parse_policy(row)


REFUSALS = {'schema_version': 'unknown', 'enabled': 'yes', 'campaign_id': '../bad', 'revision': 0,
            'timezone': 'UTC', 'sidecar': {'enabled': True, 'release_manifest': 'fixture'},
            'policy_name': '', 'policy_revision': 0, 'market_ids': ['nyc'],
            'band_limit_session': 3, 'band_limit_concurrent': 3, 'tokens': ['MAYBE'],
            'quote_offset_pusd': '.051', 'requote_distance_cents': ['3', '1'],
            'leg_price_range': ['.16', '.8'], 'per_order_cap_pusd': '15.800001',
            'per_band_cap_pusd': '19.600001', 'share_many_range': ['.14', '.7'],
            'start_window_toronto': ['15:00:00', '15:15:00'], 'trading_end_toronto': '09:00:00',
            'max_session_seconds': 299, 'learning_dates': ['2026-11-09', '2026-11-17'],
            'transition_no_entry_date': '2026-11-15', 'confirmation_dates': ['2026-11-16', '2027-01-01'],
            'nominal_confirmation_dates': 35, 'success_looks': ['2026-12-29T18:00:00-05:00']}


@pytest.mark.parametrize('field', sorted(VARIABLE))
def test_each_variable_field_accepts_supported_and_refuses_bad_value(field):
    assert set(REFUSALS) == VARIABLE
    row = example_policy()
    assert parse_policy(row).raw[field] == row[field]
    row[field] = deepcopy(REFUSALS[field])
    with pytest.raises(ValueError):
        parse_policy(row)


@pytest.mark.parametrize('offset,window,tokens', [('.005', ['.5', '2'], ['YES']),
                                               ('.025', ['2', '4'], ['NO']),
                                               ('.05', ['3', '6'], ['CHEAP']),
                                               ('.015', ['1', '3'], ['YES', 'NO'])])
def test_supported_adaptive_quote_and_token_fields(offset, window, tokens):
    row = example_policy()
    row.update(quote_offset_pusd=offset, requote_distance_cents=window, tokens=tokens, policy_revision=2)
    assert parse_policy(row).raw['quote_offset_pusd'] == offset


def test_late_start_shortens_exposure_and_never_moves_fixed_end():
    entry = parse_policy(example_policy()).entries[0]
    late = entry.start + timedelta(minutes=14, seconds=59)
    assert entry.permits(late)
    assert entry.session_end(late) == entry.fixed_end == entry.start + timedelta(hours=6)
    assert not entry.permits(entry.end)
    assert not entry.permits(entry.start - timedelta(microseconds=1))
    assert (entry.session_end(late) - late).total_seconds() == 20701


def test_unknown_extra_field_is_refused_instead_of_silent_fallback():
    row = example_policy()
    row['unimplemented_adaptation'] = True
    with pytest.raises(ValueError, match='policy_fields'):
        parse_policy(row)


def test_confirmation_population_cannot_shrink_to_remove_idle_dates():
    row = example_policy()
    row.update(confirmation_dates=['2026-11-18', '2026-12-22'], nominal_confirmation_dates=35)
    with pytest.raises(ValueError, match='unsupported_confirmation_dates'):
        parse_policy(row)


@pytest.mark.parametrize('markets', [[{}], [None], ['toronto', 'toronto'], ['toronto', 'denver']])
def test_malformed_or_noncanonical_market_list_is_an_explicit_refusal(markets):
    row = example_policy()
    row['market_ids'] = markets
    with pytest.raises(ValueError, match='unsupported_market_ids'):
        parse_policy(row)


@pytest.mark.parametrize('window,seconds', [(['18:50:00', '19:15:00'], 300),
                                          (['17:30:00', '17:51:00'], 3600)])
def test_unsupported_UTC_window_refuses_before_any_date_can_be_consumed(window, seconds):
    row = example_policy()
    row.update(start_window_toronto=window, trading_end_toronto='20:00:00', max_session_seconds=seconds)
    with pytest.raises(ValueError, match='unsupported_utc_session_boundary'):
        parse_policy(row)


def test_latest_start_can_end_exactly_at_the_existing_UTC_cutoff():
    row = example_policy()
    row.update(start_window_toronto=['18:30:00', '18:45:00'], trading_end_toronto='20:00:00', max_session_seconds=300)
    entry = parse_policy(row).entries[0]
    assert entry.permits(entry.start) and entry.permits(entry.end - timedelta(microseconds=1))
