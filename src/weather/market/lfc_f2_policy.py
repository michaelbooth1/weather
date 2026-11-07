"""Owner-approved T033 Appendix A fields for the F2 campaign (B036).

The v0.1 parser remains the F0 compatibility contract. This explicit v0.2
protocol uses native-principal accounting and a reproducible per-city selection.
Unsupported field values refuse; there are no implicit economic defaults.
"""
from datetime import date, datetime, timedelta, timezone

from weather.market import lfc_constants as C
from weather.market.lfc_accounting import quantity
from weather.market.lfc_campaign_policy import (Campaign, Entry, EARLIEST, ID, MIN_SESSION_SECONDS,
                                               PolicyRefused, ZONE, exact_keys, wall_time)
from weather.market.lfc_capital import CapitalBook, CapitalRefused, MODE


SCHEMA = 'lfc_campaign_policy_v0.2'
REFERENCE = 'f531395522d0b0a37495185b2750164008fe586a'
SELECTION = 'F0_eligible_then_max_predicted_360_minute_reward_per_city; ties_condition_id_ascending; same_rank_for_cash_admission'
ELIGIBILITY = 'F0_reference_filters_restricted_to_configured_DTE; native_reward_minimum_must_fit_20_shares'
FIXED = {'platform': 'polymarket_international', 'bands_per_event': 1, 'events_per_city': 1,
         'local_event_dte': [1],  # Owner-approved T+1 only (B039).
         'selection': SELECTION, 'selection_reference_git_sha': REFERENCE, 'order_side': 'BUY',
         'shares_per_leg': '20', 'tick_pusd': '0.01', 'price_rounding': 'floor_outward_to_tick',
         'eligibility_profile': ELIGIBILITY, 'predicted_reward_floor': None, 'post_only': True,
         'on_first_band_fill': 'cancel_remaining_orders_in_band_and_retire_band',
         'replace_retired_band': False, 'inventory_exit': 'hold_to_venue_resolution_and_redemption',
         'gtd_tail_seconds': 60, 'max_sessions_per_day': 1, 'concurrent_sessions': 1,
         'owner_funding_ceiling_pusd': '300', 'topups': False, 'capital_mode': MODE,
         'profit_reinvestment': False, 'daily_loss_stop': None, 'cumulative_loss_stop_below_total': None,
         'evidence_route': 'actual_live_cash_proposed_amendment', 'secondary_policy': None,
         'economic_minimum_total_pusd': '0', 'economic_minimum_zero_is_strict': True,
         'dependence_method': 'campaign_support_bound_v1', 'family_alpha': '0.05',
         'freeze_deadline_toronto': '2026-11-16T18:00:00-05:00',
         'evidence_cutoff_toronto': '2026-12-28T12:00:00-05:00',
         'economic_changes_after_freeze': 'successor_learning_only'}
VARIABLE = {'schema_version', 'enabled', 'campaign_id', 'revision', 'timezone', 'sidecar',
            'policy_name', 'policy_revision', 'market_ids', 'band_limit_session',
            'band_limit_concurrent', 'tokens', 'quote_offset_pusd', 'requote_distance_cents',
            'leg_price_range', 'per_order_cap_pusd', 'per_band_cap_pusd', 'share_many_range',
            'start_window_toronto', 'trading_end_toronto', 'max_session_seconds', 'learning_dates',
            'transition_no_entry_date', 'confirmation_dates', 'nominal_confirmation_dates', 'success_looks'}
ECONOMIC_FIELDS = frozenset(FIXED) | (VARIABLE - {'schema_version', 'enabled', 'campaign_id', 'revision', 'sidecar'})


def refuse(code):
    raise PolicyRefused(code)


def bounds(row, key, low, high):
    value = row[key]
    if not isinstance(value, list) or len(value) != 2:
        refuse('unsupported_' + key)
    values = tuple(quantity(v) for v in value)
    if not low <= values[0] <= values[1] <= high:
        refuse('unsupported_' + key)
    return values


class F2Campaign(Campaign):
    @property
    def f2(self):
        return True

    @property
    def terms(self):
        # Adapter only. The new native rail owns admission; no old hidden stops.
        return {'budget_pusd': self.raw['owner_funding_ceiling_pusd'], 'shares_per_leg': self.raw['shares_per_leg'],
                'k_max': self.raw['band_limit_session'], 'per_order_cap': self.raw['per_order_cap_pusd'],
                'per_band_cap': self.raw['per_band_cap_pusd'], 'per_date_cap': None, 'daily_loss_cap': None,
                'realised_stop': None, 'unknown_settlement': 'full_loss', 'max_sessions': None,
                'last_start_local_date': self.raw['confirmation_dates'][1], 'fill_retires': 'band'}

    def cost_gate(self, ledger, entry, reserve, *, own_resting=0):
        try:
            return CapitalBook(ledger).gate(reserve=reserve, own_resting=own_resting)
        except CapitalRefused as exc:
            raise PolicyRefused(str(exc)) from None


def parse_f2(row):
    exact_keys(row, set(FIXED) | VARIABLE)
    if row['schema_version'] != SCHEMA or type(row['enabled']) is not bool or row['timezone'] != ZONE.key:
        refuse('policy_identity')
    for key in ('campaign_id', 'policy_name'):
        if not isinstance(row[key], str) or not ID.fullmatch(row[key]):
            refuse('policy_identity')
    for key in ('revision', 'policy_revision'):
        if type(row[key]) is not int or row[key] < 1:
            refuse('policy_revision')
    for key, expected in FIXED.items():
        value = row[key]
        # Numeric JSON strings and exact booleans have distinct contracts.
        if (type(value) is not type(expected) or value != expected or
                key == 'local_event_dte' and any(type(day) is not int for day in value)):
            refuse('unsupported_' + key)
    if (not isinstance(row['market_ids'], list) or not row['market_ids'] or
            any(not isinstance(city, str) for city in row['market_ids']) or
            row['market_ids'] != sorted(set(row['market_ids'])) or
            any(city not in ('denver', 'toronto') for city in row['market_ids'])):
        refuse('unsupported_market_ids')
    if (type(row['band_limit_session']) is not int or row['band_limit_session'] not in (1, 2) or
            type(row['band_limit_concurrent']) is not int or row['band_limit_concurrent'] != row['band_limit_session']):
        refuse('unsupported_band_limits')
    if row['tokens'] not in (['YES', 'NO'], ['YES'], ['NO'], ['CHEAP']):
        refuse('unsupported_tokens')
    if not quantity('0.005') <= quantity(row['quote_offset_pusd']) <= quantity('0.05'):
        refuse('unsupported_quote_offset_pusd')
    if (quantity(row['quote_offset_pusd']) * 1000) % 1:
        refuse('unsupported_quote_offset_precision')
    bounds(row, 'requote_distance_cents', quantity('0.5'), quantity('6'))
    bounds(row, 'leg_price_range', quantity('.17'), quantity('.80'))
    bounds(row, 'share_many_range', quantity('.15'), quantity('.70'))
    for key, ceiling in [('per_order_cap_pusd', '15.80'), ('per_band_cap_pusd', '19.60')]:
        if not 0 < quantity(row[key]) <= quantity(ceiling):
            refuse('unsupported_' + key)
    seconds = row['max_session_seconds']
    if type(seconds) is not int or not MIN_SESSION_SECONDS <= seconds <= 21600:
        refuse('unsupported_max_session_seconds')
    window = row['start_window_toronto']
    if not isinstance(window, list) or len(window) != 2:
        refuse('toronto_start_window')
    begin, finish, stop = wall_time(window[0]), wall_time(window[1]), wall_time(row['trading_end_toronto'])
    if not begin < finish < stop:
        refuse('toronto_start_window')
    ranges = []
    for key in ('learning_dates', 'confirmation_dates'):
        pair = row[key]
        approved = (['2026-11-09', '2026-11-15'] if key == 'learning_dates' else ['2026-11-17', '2026-12-22'])
        if pair != approved:
            refuse('unsupported_' + key)
        if not isinstance(pair, list) or len(pair) != 2:
            refuse('unsupported_' + key)
        try:
            start, end = map(date.fromisoformat, pair)
        except (ValueError, TypeError):
            refuse('unsupported_' + key)
        if not date(2026, 11, 9) <= start <= end <= date(2026, 12, 22):
            refuse('unsupported_' + key)
        ranges.append((start, end))
    try:
        transition = date.fromisoformat(row['transition_no_entry_date'])
    except (ValueError, TypeError):
        refuse('transition_date')
    if transition != date(2026, 11, 16) or not ranges[0][1] < transition < ranges[1][0]:
        refuse('transition_date')
    if (type(row['nominal_confirmation_dates']) is not int or
            row['nominal_confirmation_dates'] != 36 or
            row['nominal_confirmation_dates'] != (ranges[1][1] - ranges[1][0]).days + 1):
        refuse('nominal_confirmation_dates')
    if row['success_looks'] != ['2026-12-28T18:00:00-05:00']:
        refuse('unsupported_success_looks')
    if row['sidecar'] is not None:
        exact_keys(row['sidecar'], ('enabled', 'release_manifest'))
        if row['sidecar']['enabled'] is not False or not isinstance(row['sidecar']['release_manifest'], str):
            refuse('unsupported_sidecar_interval_coverage')
    entries = []
    for first, last in ranges:
        day = first
        while day <= last:
            start = datetime.combine(day, begin, ZONE).astimezone(timezone.utc)
            end = datetime.combine(day, finish, ZONE).astimezone(timezone.utc)
            fixed = datetime.combine(day, stop, ZONE).astimezone(timezone.utc)
            if (end - start).total_seconds() > 7200 or (fixed - end).total_seconds() < MIN_SESSION_SECONDS:
                refuse('entry_window_or_duration')
            # Every advertised start must fit the controller's existing UTC
            # day/cutoff contract. Refuse here, before tick can claim or skip a
            # date merely because an early segment of its window cannot run.
            latest_end = min(end + timedelta(seconds=seconds), fixed)
            if latest_end > datetime.combine(start.date(), C.HARD_STOP_UTC, tzinfo=timezone.utc):
                refuse('unsupported_utc_session_boundary')
            # Monday retains its separately pinned F0 authority and terms.
            if start >= EARLIEST:
                entries.append(Entry('f2-' + day.isoformat(), day.isoformat(), start, end, seconds, fixed, True))
            day += timedelta(days=1)
    if not entries:
        refuse('finite_entries_required')
    return F2Campaign(row, tuple(entries))


def example_policy():
    return {**FIXED, 'schema_version': SCHEMA, 'enabled': False, 'campaign_id': 'lfc-f2-202611',
            'revision': 1, 'timezone': ZONE.key, 'sidecar': None, 'policy_name': 'DT-T1-Paired20-K2',
            'policy_revision': 1, 'market_ids': ['denver', 'toronto'], 'local_event_dte': [1],
            'band_limit_session': 2, 'band_limit_concurrent': 2, 'tokens': ['YES', 'NO'],
            'quote_offset_pusd': '0.015', 'requote_distance_cents': ['1', '3'],
            'leg_price_range': ['0.17', '0.80'], 'per_order_cap_pusd': '15.80', 'per_band_cap_pusd': '19.60',
            'share_many_range': ['0.15', '0.70'], 'start_window_toronto': ['09:00:00', '09:15:00'],
            'trading_end_toronto': '15:00:00', 'max_session_seconds': 21600,
            'learning_dates': ['2026-11-09', '2026-11-15'], 'transition_no_entry_date': '2026-11-16',
            'confirmation_dates': ['2026-11-17', '2026-12-22'], 'nominal_confirmation_dates': 36,
            'success_looks': ['2026-12-28T18:00:00-05:00']}


def support_table():
    return {'schema_version': SCHEMA, 'fields': sorted(set(FIXED) | VARIABLE), 'fixed_values': FIXED,
            'band_limits': [1, 2], 'bands_per_event': 1, 'events_per_city': 1,
            'market_ids': ['denver', 'toronto'], 'local_event_dte_subset': [1],
            'tokens': [['YES', 'NO'], ['YES'], ['NO'], ['CHEAP']],
            'quote_offset_pusd': {'min': '.005', 'max': '.05', 'step': '.001'},
            'requote_distance_cents': {'min': '.5', 'max': '6', 'ordered_inclusive_pair': True},
            'leg_price_range': ['.17', '.80'], 'share_many_range': ['.15', '.70'],
            'per_order_cap_pusd_max': '15.80', 'per_band_cap_pusd_max': '19.60',
            'duration_seconds': [MIN_SESSION_SECONDS, 21600], 'late_start_shortens_fixed_end': True,
            'latest_session_end_utc': C.HARD_STOP_UTC.isoformat(), 'utc_date_crossing': False,
            'last_entry_date': '2026-12-22', 'transition_has_no_entry': True,
            'funding_native_max': 300000000, 'native_decimals': 6,
            'legacy_ledger_bridge_required': True, 'revisions_apply_to_next_unclaimed_entry': True}
