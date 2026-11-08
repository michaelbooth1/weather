"""Owner-editable autostart policy. Parsing grants no exchange capability."""
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
import hashlib
import re
from zoneinfo import ZoneInfo

from weather.market import lfc_constants as C
from weather.market.lfc_accounting import quantity
from weather.market.lfc_recording_io import read_bytes, strict_json
from weather.market.mm_stage2_hold import digest


POLICY_SCHEMA = 'lfc_campaign_policy_v0.1'
PROTOCOL = 'lfc_autostart_v1'
ZONE = ZoneInfo('America/Toronto')
EARLIEST = datetime(2026, 11, 10, tzinfo=timezone.utc)
ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z')
SIDECAR_SUPPORTED = False  # B032 R3: whole-private-session interval coverage is not qualified.
MIN_SESSION_SECONDS = 300  # 180 s pre-POST horizon plus 120 s opening-read headroom, fixture-qualified.


class PolicyRefused(ValueError):
    pass


def timestamp(text):
    if not isinstance(text, str) or not text.endswith('Z'):
        raise PolicyRefused('utc_Z_required')
    try:
        result = datetime.fromisoformat(text[:-1] + '+00:00')
    except ValueError:
        raise PolicyRefused('utc_unreadable') from None
    return result


def exact_keys(row, keys):
    if not isinstance(row, dict) or set(row) != set(keys):
        raise PolicyRefused('policy_fields')


@dataclass(frozen=True)
class Entry:
    id: str
    local_date: str
    start: datetime
    end: datetime
    seconds: int
    fixed_end: datetime | None = None
    shorten_to_fixed_end: bool = False

    def permits(self, now):
        if type(self.seconds) is not int or not MIN_SESSION_SECONDS <= self.seconds <= C.SESSION_SECONDS:
            raise PolicyRefused('unsupported_duration_seconds')
        planned = self.session_end(now)
        return (self.start <= now < self.end and planned - now >= timedelta(seconds=MIN_SESSION_SECONDS) and
                (self.fixed_end is None or planned <= self.fixed_end) and
                planned <= datetime.combine(now.date(), time(23, 50), tzinfo=timezone.utc))

    def session_end(self, now):
        end = now + timedelta(seconds=self.seconds)
        return min(end, self.fixed_end) if self.shorten_to_fixed_end and self.fixed_end is not None else end


@dataclass(frozen=True)
class Campaign:
    raw: dict
    entries: tuple
    source_sha256: str | None = field(default=None, compare=False, repr=False)

    @property
    def f2(self):
        return False

    @property
    def sha256(self):
        return digest(self.raw)

    @property
    def terms(self):
        return self.raw['terms']

    def labels(self, local_date=None):
        lane = 'reference'
        for field, name in [('learning_dates', 'learning'), ('confirmation_dates', 'confirmation')]:
            bounds = self.raw[field]
            if local_date is not None and bounds and bounds[0] <= local_date <= bounds[1]:
                lane = name
        return {'policy_name': self.raw['policy_name'], 'policy_revision': self.raw['policy_revision'],
                'evidence_lane': lane}

    def cost_gate(self, ledger, entry, reserve, *, own_resting=0):
        """Prospective full-cost gates: no rewards, profit or settlement credits.

        daily_loss_cap is a conservative exposure bound on *both* start and
        settlement dates, including carried/unknown inventory, not a promise
        inferred from a threshold checked only after a new fill.
        """
        reserve, own = quantity(reserve), quantity(own_resting)
        committed = ledger.L() - own
        if committed < 0 or committed + reserve > quantity(self.terms['budget_pusd']):
            raise PolicyRefused('campaign_cap')
        start_date = entry.local_date
        dates = {start_date}
        for leg in ledger.legs.values():
            session = ledger.sessions[leg['session_id']]['start']
            if session.get('event_date'):
                dates.add(session['event_date'])
        for day in dates:
            cost = sum((quantity(leg['size_matched'] if leg['status'] == 'terminal' else leg['size']) *
                        quantity(leg['price']) for leg in ledger.legs.values()
                        if ledger.sessions[leg['session_id']]['start'].get('owner_local_date') == day), quantity(0))
            if day == start_date and cost - own + reserve > quantity(self.terms['per_date_cap']):
                raise PolicyRefused('per_date_cap')
        daily = self.terms['daily_loss_cap']
        if daily is not None and committed + reserve > quantity(daily):
            raise PolicyRefused('daily_loss_cap')
        realised = self.terms['realised_stop']
        # Unknown settlement is charged as full cost. No automatic realised
        # payout credit is supported in this release, even for known winners.
        if realised is not None and committed + reserve > quantity(realised):
            raise PolicyRefused('realised_stop_prospective')


def wall_time(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-2][0-9]:[0-5][0-9]:[0-5][0-9]', value):
        raise PolicyRefused('toronto_time_format')
    try:
        return time.fromisoformat(value)
    except ValueError:
        raise PolicyRefused('toronto_time_format') from None


def parse_policy(row):
    if isinstance(row, dict) and row.get('schema_version') == 'lfc_campaign_policy_v0.3':
        from weather.market.lfc_f2_breadth import parse_breadth
        return parse_breadth(row)
    if isinstance(row, dict) and row.get('schema_version') == 'lfc_campaign_policy_v0.2':
        from weather.market.lfc_f2_policy import parse_f2
        return parse_f2(row)
    exact_keys(row, ('schema_version', 'enabled', 'campaign_id', 'revision', 'timezone', 'terms', 'entries', 'sidecar',
                     'policy_name', 'policy_revision', 'local_event_dte', 'band_limit_session', 'band_limit_concurrent',
                     'bands_per_event', 'start_window_toronto', 'trading_end_toronto', 'max_sessions_per_day',
                     'concurrent_sessions', 'max_session_seconds', 'learning_dates', 'confirmation_dates', 'capital_mode'))
    if (row['schema_version'] != POLICY_SCHEMA or type(row['enabled']) is not bool or
            not isinstance(row['campaign_id'], str) or not ID.fullmatch(row['campaign_id']) or
            type(row['revision']) is not int or row['revision'] < 1 or row['timezone'] != ZONE.key):
        raise PolicyRefused('policy_identity')
    if (not isinstance(row['policy_name'], str) or not ID.fullmatch(row['policy_name']) or
            type(row['policy_revision']) is not int or row['policy_revision'] < 1):
        raise PolicyRefused('policy_name_or_revision')
    for key in ('band_limit_session', 'band_limit_concurrent', 'bands_per_event', 'max_sessions_per_day', 'concurrent_sessions'):
        if type(row[key]) is not int or row[key] != 1:
            raise PolicyRefused('unsupported_' + key)
    if (not isinstance(row['local_event_dte'], list) or not row['local_event_dte'] or
            any(type(day) is not int or day not in (1, 2) for day in row['local_event_dte']) or
            row['local_event_dte'] != sorted(set(row['local_event_dte']))):
        raise PolicyRefused('unsupported_local_event_dte')
    if type(row['max_session_seconds']) is not int or not MIN_SESSION_SECONDS <= row['max_session_seconds'] <= C.SESSION_SECONDS:
        raise PolicyRefused('unsupported_max_session_seconds')
    if row['capital_mode'] != 'committed_cost_no_recycling':
        raise PolicyRefused('unsupported_capital_mode')
    window = row['start_window_toronto']
    if window is not None and (not isinstance(window, list) or len(window) != 2 or
                                not wall_time(window[0]) < wall_time(window[1])):
        raise PolicyRefused('toronto_start_window')
    fixed_end = None if row['trading_end_toronto'] is None else wall_time(row['trading_end_toronto'])
    ranges = []
    for key in ('learning_dates', 'confirmation_dates'):
        bounds = row[key]
        if not isinstance(bounds, list) or len(bounds) not in (0, 2):
            raise PolicyRefused(key + '_range')
        if bounds:
            try:
                begin, finish = (date.fromisoformat(value) for value in bounds)
            except (ValueError, TypeError):
                raise PolicyRefused(key + '_range') from None
            if begin > finish or finish > C.LAST_START_LOCAL_DATE:
                raise PolicyRefused('unsupported_' + key)
            ranges.append((begin, finish))
    if len(ranges) == 2 and max(ranges[0][0], ranges[1][0]) <= min(ranges[0][1], ranges[1][1]):
        raise PolicyRefused('learning_confirmation_overlap')
    terms = row['terms']
    exact_keys(terms, ('budget_pusd', 'shares_per_leg', 'k_max', 'per_order_cap', 'per_band_cap', 'per_date_cap',
                       'daily_loss_cap', 'realised_stop', 'unknown_settlement', 'max_sessions',
                       'last_start_local_date', 'fill_retires'))
    # Qualified first release: unchanged F0 size/band ceiling. Unsupported
    # expansion is an explicit refusal, never a silently truncated selection.
    if quantity(terms['shares_per_leg']) != C.PILOT_SIZE or type(terms['k_max']) is not int or terms['k_max'] != 1:
        raise PolicyRefused('unsupported_size_or_band_count')
    for key, ceiling in [('budget_pusd', C.CAP_PUSD), ('per_order_cap', C.PER_ORDER_CAP_PUSD),
                         ('per_band_cap', C.PER_BAND_CAP_PUSD)]:
        if not 0 < quantity(terms[key]) <= ceiling:
            raise PolicyRefused('unsupported_' + key)
    for key in ('per_date_cap', 'daily_loss_cap', 'realised_stop'):
        if terms[key] is None and key != 'per_date_cap':
            continue
        if not 0 < quantity(terms[key]) <= C.CAP_PUSD:
            raise PolicyRefused('unsupported_' + key)
    if (terms['unknown_settlement'] != 'full_loss' or terms['fill_retires'] != 'band' or
            type(terms['max_sessions']) is not int or not 1 <= terms['max_sessions'] <= C.MAX_SESSIONS):
        raise PolicyRefused('unsupported_campaign_terms')
    try:
        last = date.fromisoformat(terms['last_start_local_date'])
    except (ValueError, TypeError):
        raise PolicyRefused('last_date') from None
    if last > C.LAST_START_LOCAL_DATE:
        raise PolicyRefused('unsupported_last_start_date')
    entries, ids, days = [], set(), set()
    if not isinstance(row['entries'], list) or not 1 <= len(row['entries']) <= 32:
        raise PolicyRefused('finite_entries_required')
    for item in row['entries']:
        exact_keys(item, ('id', 'local_date', 'window_start_utc', 'window_end_utc', 'duration_seconds'))
        if not isinstance(item['id'], str) or not ID.fullmatch(item['id']) or item['id'] in ids:
            raise PolicyRefused('entry_id')
        start, end = timestamp(item['window_start_utc']), timestamp(item['window_end_utc'])
        requested_seconds = item['duration_seconds']
        if type(requested_seconds) is not int or not MIN_SESSION_SECONDS <= requested_seconds <= C.SESSION_SECONDS:
            raise PolicyRefused('entry_window_or_duration')
        seconds = min(requested_seconds, row['max_session_seconds'])
        local = start.astimezone(ZONE)
        deadline = None if fixed_end is None else datetime.combine(local.date(), fixed_end, ZONE).astimezone(timezone.utc)
        if (start < EARLIEST or
                not start < end <= start + timedelta(hours=2) or start.astimezone(ZONE).date().isoformat() != item['local_date'] or
                end.astimezone(ZONE).date().isoformat() != item['local_date'] or item['local_date'] in days or
                date.fromisoformat(item['local_date']) > last or
                end + timedelta(seconds=seconds) > datetime.combine(start.date(), time(23, 50), tzinfo=timezone.utc)):
            raise PolicyRefused('entry_window_or_duration')
        if window is not None and (local.time() != wall_time(window[0]) or
                                   end.astimezone(ZONE).time() != wall_time(window[1])):
            raise PolicyRefused('entry_toronto_window_differs')
        if ranges and not any(begin <= local.date() <= finish for begin, finish in ranges):
            raise PolicyRefused('entry_outside_learning_confirmation_dates')
        if deadline is not None and end + timedelta(seconds=seconds) > deadline:
            raise PolicyRefused('trading_end_before_full_session')
        entries.append(Entry(item['id'], item['local_date'], start, end, seconds, deadline))
        ids.add(item['id'])
        days.add(item['local_date'])
    if row['sidecar'] is not None:
        exact_keys(row['sidecar'], ('enabled', 'release_manifest'))
        if type(row['sidecar']['enabled']) is not bool or not isinstance(row['sidecar']['release_manifest'], str):
            raise PolicyRefused('sidecar_policy')
        if row['sidecar']['enabled'] and not SIDECAR_SUPPORTED:
            raise PolicyRefused('unsupported_sidecar_interval_coverage')
    return Campaign(row, tuple(sorted(entries, key=lambda x: x.start)))


def load_policy(path):
    from weather.operations.live_path_security import validate_regular_nonreparse_file
    raw = read_bytes(validate_regular_nonreparse_file(Path(path).absolute()), 65536)
    return replace(parse_policy(strict_json(raw)), source_sha256=hashlib.sha256(raw).hexdigest())


def parameter_support():
    """JSON support table sealed with the release, independent of policy edits."""
    from weather.market.lfc_f2_policy import support_table
    from weather.market.lfc_f2_breadth import support_table as breadth_support
    return {
        'f2': support_table(), 'f2_breadth': breadth_support(),
        'terms.budget_pusd': {'exclusive_min': '0', 'max': str(C.CAP_PUSD)},
        'terms.shares_per_leg': {'values': [str(C.PILOT_SIZE)]},
        'terms.k_max': {'values': [1]},
        'terms.per_order_cap': {'exclusive_min': '0', 'max': str(C.PER_ORDER_CAP_PUSD)},
        'terms.per_band_cap': {'exclusive_min': '0', 'max': str(C.PER_BAND_CAP_PUSD)},
        'terms.per_date_cap': {'exclusive_min': '0', 'max': str(C.CAP_PUSD), 'scope': 'start_date_new_cost'},
        'terms.daily_loss_cap': {'nullable': True, 'exclusive_min': '0', 'max': str(C.CAP_PUSD),
                                 'scope': 'all_carried_cost_plus_new_reserve_no_credit'},
        'terms.realised_stop': {'nullable': True, 'exclusive_min': '0', 'max': str(C.CAP_PUSD),
                                'scope': 'all_carried_cost_plus_new_reserve_no_credit'},
        'terms.unknown_settlement': {'values': ['full_loss']},
        'terms.max_sessions': {'min': 1, 'max': C.MAX_SESSIONS, 'includes_previous_counted_sessions': True},
        'terms.last_start_local_date': {'max': C.LAST_START_LOCAL_DATE.isoformat()},
        'terms.fill_retires': {'values': ['band']},
        'local_event_dte': {'sorted_nonempty_subset': [1, 2], 'checked': 'every_placement_and_requote'},
        **{key: {'values': [1]} for key in ('band_limit_session', 'band_limit_concurrent', 'bands_per_event',
                                           'max_sessions_per_day', 'concurrent_sessions')},
        'max_session_seconds': {'min': MIN_SESSION_SECONDS, 'max': C.SESSION_SECONDS,
                                'initial_read_headroom_seconds': 120, 'minimum_post_remaining_seconds': 180},
        'entries': {'min': 1, 'max': 32, 'earliest_utc': EARLIEST.isoformat(),
                    'window': 'half_open_explicit_UTC_Z', 'max_window_seconds': 7200,
                    'duration_min_seconds': MIN_SESSION_SECONDS, 'duration_max_seconds': C.SESSION_SECONDS,
                    'utc_hard_end': '23:50:00', 'unique_toronto_dates': True},
        'start_window_toronto': {'nullable': True, 'format': 'HH:MM:SS_pair_matches_each_UTC_entry'},
        'trading_end_toronto': {'nullable': True, 'format': 'HH:MM:SS_fixed_absolute_end',
                                'full_duration_must_fit': True},
        **{key: {'format': 'empty_or_inclusive_disjoint_date_pair', 'max': C.LAST_START_LOCAL_DATE.isoformat()}
           for key in ('learning_dates', 'confirmation_dates')},
        'capital_mode': {'values': ['committed_cost_no_recycling']},
        'policy_name': {'format': 'identifier_1_to_64_characters'},
        'policy_revision': {'min': 1, 'economic_change_requires_increase': True},
        'sidecar': {'nullable': True, 'enabled_values': [False],
                    'scope': 'unsupported_until_private_session_interval_coverage_is_qualified'},
    }
