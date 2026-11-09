"""B072 Pin B policy; retained v0.1-v0.3 policies keep their old contracts."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone

from weather.market import lfc_constants as C
from weather.market import lfc_f2_breadth as breadth
from weather.market import lfc_f2_policy as legacy
from weather.market.lfc_campaign_policy import Entry, EARLIEST, MIN_SESSION_SECONDS, ZONE, exact_keys, wall_time


SCHEMA = 'lfc_campaign_policy_v0.4'
FIELDS = frozenset({'max_submits_per_band', 'max_requotes_per_band', 'learning_leg_arms', 'confirmation_leg_arm'})
SCHEDULE = {'learning_dates': ['2026-11-09', '2026-11-22'], 'transition_no_entry_date': None,
            'confirmation_dates': ['2026-11-23', '2026-12-22'], 'nominal_confirmation_dates': 30,
            'freeze_deadline_toronto': '2026-11-22T18:00:00-05:00'}
MAX_SECONDS = 35100


def enabled(policy):
    return policy.raw.get('schema_version') == SCHEMA


def session_limits(ledger, session_id):
    """Only a ledger-bound Pin B start grants the larger private-proof budget."""
    row = ledger.sessions[session_id]['start']
    if row.get('autostart_policy_schema') != SCHEMA:
        return 10, 4
    if (type(row.get('max_submits_per_band')) is not int or row['max_submits_per_band'] != 40 or
            type(row.get('max_requotes_per_band')) is not int or row['max_requotes_per_band'] != 16):
        raise ValueError('pinb_session_limit_binding')
    return 40, 16


class PinBEntry(Entry):
    def permits(self, now):
        if type(self.seconds) is not int or not MIN_SESSION_SECONDS <= self.seconds <= MAX_SECONDS:
            legacy.refuse('unsupported_duration_seconds')
        planned = self.session_end(now)
        hard = datetime.combine(now.astimezone(timezone.utc).date(), C.HARD_STOP_UTC, timezone.utc)
        return (self.start <= now < self.end and planned-now >= timedelta(seconds=MIN_SESSION_SECONDS) and
                planned <= self.fixed_end and planned <= hard)


def parse_pinb(row):
    if 'sleeve_loss_basis' not in row:
        legacy.refuse('explicit_sleeve_loss_basis_required')
    exact_keys(row, set(legacy.FIXED) | legacy.VARIABLE | breadth.FIELDS | FIELDS)
    if row['schema_version'] != SCHEMA:
        legacy.refuse('policy_identity')
    for key, value in SCHEDULE.items():
        if type(row[key]) is not type(value) or row[key] != value:
            legacy.refuse('unsupported_' + key)
    for key, value in [('max_submits_per_band', 40), ('max_requotes_per_band', 16)]:
        if type(row[key]) is not int or row[key] != value:
            legacy.refuse('unsupported_' + key)
    choices = row['learning_leg_arms']
    if (not isinstance(choices, list) or not 1 <= len(choices) <= 2 or
            any(not isinstance(v, str) or v not in {'paired', 'cheap'} for v in choices) or
            len(set(choices)) != len(choices)):
        legacy.refuse('unsupported_learning_leg_arms')
    if row['confirmation_leg_arm'] not in ('paired', 'cheap'):
        legacy.refuse('unsupported_confirmation_leg_arm')
    if row['tokens'] != ['YES', 'NO']:
        legacy.refuse('unsupported_pinb_tokens')
    seconds = row['max_session_seconds']
    if type(seconds) is not int or not MIN_SESSION_SECONDS <= seconds <= MAX_SECONDS:
        legacy.refuse('unsupported_max_session_seconds')
    if wall_time(row['trading_end_toronto']) > wall_time('18:45:00'):
        legacy.refuse('unsupported_trading_end_toronto')
    # Each transformed field has its own Pin B validation above. Every other
    # value still traverses the existing breadth, money and eligibility parser.
    reference = deepcopy({k: v for k, v in row.items() if k not in FIELDS})
    old = legacy.example_policy()
    reference.update({key: old[key] for key in SCHEDULE})
    reference.update(schema_version=breadth.SCHEMA, max_session_seconds=min(seconds, 21600))
    breadth.parse_breadth(reference)
    begin, finish = map(wall_time, row['start_window_toronto'])
    stop = wall_time(row['trading_end_toronto'])
    entries = []
    for key in ('learning_dates', 'confirmation_dates'):
        day, last = map(date.fromisoformat, row[key])
        while day <= last:
            start = datetime.combine(day, begin, ZONE).astimezone(timezone.utc)
            end = datetime.combine(day, finish, ZONE).astimezone(timezone.utc)
            fixed = datetime.combine(day, stop, ZONE).astimezone(timezone.utc)
            latest = min(end+timedelta(seconds=seconds), fixed)
            if latest > datetime.combine(start.date(), C.HARD_STOP_UTC, timezone.utc):
                legacy.refuse('unsupported_utc_session_boundary')
            if start >= EARLIEST:
                entries.append(PinBEntry('f2-b-'+day.isoformat(), day.isoformat(), start, end, seconds, fixed, True))
            day += timedelta(days=1)
    return legacy.F2Campaign(deepcopy(row), tuple(entries))


def example_policy():
    return {**breadth.example_policy(), **deepcopy(SCHEDULE), 'schema_version': SCHEMA,
        'policy_name': 'Builtin-T1-PairedCheap20-Continue30', 'policy_revision': 5, 'revision': 2,
        'trading_end_toronto': '18:45:00', 'max_session_seconds': MAX_SECONDS,
        'max_submits_per_band': 40, 'max_requotes_per_band': 16,
        'learning_leg_arms': ['paired', 'cheap'], 'confirmation_leg_arm': 'paired',
        'per_band_daily_filled_cap_pusd': '30'}


def support_table():
    return {**breadth.support_table(), 'schema_version': SCHEMA,
        'fields': sorted(set(legacy.FIXED) | legacy.VARIABLE | breadth.FIELDS | FIELDS),
        'duration_seconds': [MIN_SESSION_SECONDS, MAX_SECONDS], 'trading_end_toronto_max': '18:45:00',
        'max_submits_per_band': 40, 'max_requotes_per_band': 16, 'schedule': SCHEDULE,
        'learning_leg_arms': ['paired', 'cheap'], 'confirmation_leg_arm': ['paired', 'cheap']}


def upgrade_policy(policy):
    """Prepare a disabled successor file; never enroll, arm or reset a root."""
    if policy.raw.get('schema_version') not in {legacy.SCHEMA, breadth.SCHEMA}:
        legacy.refuse('migration_requires_pina_policy')
    row = {**deepcopy(policy.raw), **deepcopy(SCHEDULE), 'schema_version': SCHEMA, 'enabled': False,
           'policy_name': example_policy()['policy_name'], 'revision': policy.raw['revision']+1,
           'policy_revision': policy.raw['policy_revision']+1, 'tokens': ['YES', 'NO'],
           'trading_end_toronto': '18:45:00', 'max_session_seconds': MAX_SECONDS,
           'max_submits_per_band': 40, 'max_requotes_per_band': 16,
           'learning_leg_arms': ['paired', 'cheap'], 'confirmation_leg_arm': 'paired',
           'learning_quote_offsets_pusd': ['0.015', '0.025'], 'per_band_daily_filled_cap_pusd': '30'}
    if policy.raw['schema_version'] == legacy.SCHEMA:
        # The breadth fields have no pre-v0.3 value to carry.
        for key in breadth.FIELDS:
            row.setdefault(key, deepcopy(example_policy()[key]))
    return parse_pinb(row)


def main(argv=None):
    """Owner-run, create-only policy preparation; no task/account capability."""
    import argparse
    from pathlib import Path
    from weather.market.lfc_campaign_policy import load_policy
    from weather.market.lfc_recording_io import write_new
    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument('--upgrade-from', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.upgrade_from.is_absolute() or not args.output.is_absolute():
        legacy.refuse('migration_absolute_paths_required')
    new = upgrade_policy(load_policy(args.upgrade_from))
    write_new(args.output, new.raw)
    print('Prepared disabled Pin B policy; existing account state is unchanged.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
