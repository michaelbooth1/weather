"""Owner-run D+1/D+2 incentive evidence, with read-only L2 and public v2 activity.

No private key, signing client, scheduler, order or cancellation capability.
Activity rows are cash candidates, never proof that rewards were earned on D.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
from pathlib import Path
import re
from types import SimpleNamespace

from weather.market.lfc_settlement_record import envelope, public_get, retained
from weather.market.mm_stage2_hold import utc, write_new
from weather.market.re1_payout_evidence import ReadJournal, collect_accruals
from weather.market.wallet_reader_security import CLOB
from weather.market.wallet_reader_transport import ReadTransport

REWARDS_SCHEMA = 'lfc_rewards_record_v0.1'
MAX_PAGES = 50
MAX_ROWS = 2048


class AccrualTransport(ReadTransport):
    """Reuse the reader's GET-only signing boundary, retaining raw response hashes in memory."""
    def __init__(self, fields, guard, journal, **kwargs):
        super().__init__(fields, guard, **kwargs)
        self.journal = journal

    def request(self, method, host, path, params=None, *, fresh=False):
        if host != CLOB or path not in {'/rewards/user', '/rewards/user/total'} or method != 'GET':
            raise ValueError('accrual_endpoint_refused')
        self.journal.record('wire_request', method='GET', url=self._url(host, path, params or {}),
                            hash_basis='method_LF_url', sha256=hashlib.sha256(
                                ('GET\n' + self._url(host, path, params or {})).encode()).hexdigest())
        return super().request(method, host, path, params, fresh=True)

    def _record(self, path, host, status, raw, event):
        self.journal.record('sdk_response', method='GET', path=path, status=status,
                            **(retained(raw) if raw is not None else {'sha256': None}))


class AccrualClient:
    """Minimal pagination adapter for the existing collect_accruals implementation."""
    def __init__(self, transport, signature_type):
        self.transport, self.signature_type = transport, signature_type

    def list_user_earnings_for_day(self, *, date):
        params = {'date': date, 'signature_type': self.signature_type}
        seen = set()
        for _ in range(MAX_PAGES):
            page = self.transport.request('GET', CLOB, '/rewards/user', params)
            if not isinstance(page, dict) or not isinstance(page.get('data'), list):
                raise ValueError('earnings_envelope')
            cursor = page.get('next_cursor')
            if cursor != 'LTE=' and (not isinstance(cursor, str) or not cursor or cursor in seen):
                raise ValueError('earnings_cursor')
            more = cursor != 'LTE='
            yield SimpleNamespace(items=page['data'], has_more=more, next_cursor=cursor if more else None)
            if not more:
                return
            seen.add(cursor)
            params['next_cursor'] = cursor
        raise ValueError('earnings_page_budget')

    def get_total_earnings_for_user_for_day(self, *, date):
        return self.transport.request('GET', CLOB, '/rewards/user/total',
                                      {'date': date, 'signature_type': self.signature_type})


def read_activity(maker, kind, start, end, *, get=public_get):
    """Bounded cursor walk of official v2 Activity; retain every raw envelope."""
    if not re.fullmatch(r'0x[0-9a-f]{40}', maker) or kind not in {'REWARD', 'MAKER_REBATE'}:
        raise ValueError('activity_scope')
    rows, pages, seen = [], [], set()
    params = {'user': maker, 'type': kind, 'start': int(start.timestamp()),
              'end': int(end.timestamp()) - 1, 'limit': 100, 'sort_direction': 'ASC'}
    if end <= start:
        raise ValueError('activity_window_not_open')
    for _ in range(MAX_PAGES):
        raw = get('/v2/activity', params.copy())
        page = envelope(raw)
        pages.append(retained(raw))
        for row in page['data']:
            if (row.get('proxy_wallet', '').lower() != maker or row.get('type') != kind or
                    type(row.get('timestamp')) is not int or not start.timestamp() <= row['timestamp'] < end.timestamp()):
                raise ValueError('activity_row_scope')
            rows.append(row)
        if len(rows) > MAX_ROWS:
            raise ValueError('activity_row_budget')
        pagination = page.get('pagination')
        if not isinstance(pagination, dict) or type(pagination.get('has_more')) is not bool:
            raise ValueError('activity_pagination')
        cursor = pagination.get('next_cursor')
        if pagination['has_more'] != (cursor is not None):
            raise ValueError('activity_pagination')
        if cursor is None:
            return {'rows': rows, 'pages': pages, 'pagination_complete': True,
                    'earned_period_verified': False, 'payment_verified': False}
        if not isinstance(cursor, str) or not cursor or cursor in seen:
            raise ValueError('activity_cursor')
        seen.add(cursor)
        params['cursor'] = cursor
    raise ValueError('activity_page_budget')


def recording_period(day, now):
    parsed = date.fromisoformat(day)
    if parsed.isoformat() != day:
        raise ValueError('recording_date')
    observed = utc(now)
    lag = (observed.date() - parsed).days
    if lag not in (1, 2):
        raise ValueError('rewards_record_only_d1_d2')
    return utc(day + 'T00:00:00Z'), observed, lag


def record_rewards(root, day, *, maker, conditions, venue, journal, clock, get=public_get):
    start, observed, lag = recording_period(day, clock())
    target = Path(root) / 'rewards' / f'{day}-d{lag}.json'
    if target.exists():
        raise FileExistsError('rewards_record_exists')
    conditions = sorted(set(conditions))
    if not conditions:
        raise ValueError('no_session_conditions')
    end = start + timedelta(days=1)
    accruals = []
    for condition in conditions:
        scope = dict(maker_address=maker, condition_id=condition, accrual_start_utc=start.isoformat(),
                     accrual_end_utc=end.isoformat(), cash_start_utc=start.isoformat(),
                     cash_end_utc=(start + timedelta(days=3)).isoformat())
        source, normalized, raw = collect_accruals(venue, scope, journal, clock)
        accruals.append({'condition_id': condition, 'source': source, 'accruals': normalized, 'retained': raw})
    try:
        distributions = read_activity(maker, 'REWARD', end, observed, get=get)
    except Exception as exc:
        distributions = {'pagination_complete': False, 'failure_type': type(exc).__name__, 'payment_verified': False}
    row = {'schema_version': REWARDS_SCHEMA, 'kind': 'lfc_rewards_record', 'date': day, 'pass': lag,
           'observed_at_utc': observed.isoformat(), 'maker_address': maker, 'conditions': conditions,
           'accruals': accruals, 'distributions': distributions, 'payment_verified': False,
           'wire_journal': journal.records}
    write_new(target, row)
    return row


def run_rewards_record(args):
    """Owner invocation only. The agent never calls this during implementation or verification."""
    from weather.market.lfc_ledger import Ledger, ledger_path
    from weather.market.lfc_pilot import pilot_root
    from weather.market.wallet_reader_security import load_owner_credentials
    root = args.root or pilot_root()
    clock = lambda: datetime.now(timezone.utc)
    start, observed, lag = recording_period(args.date, clock())
    if (Path(root) / 'rewards' / f'{args.date}-d{lag}.json').exists():
        raise FileExistsError('rewards_record_exists')
    ledger = Ledger.open(ledger_path(root), clock=clock)
    maker = ledger.rows[0]['maker_address'].lower()
    conditions = sorted({s['start']['condition_id'] for s in ledger.sessions.values()
                         if s['legs'] and utc(s['start']['recorded_at_utc']).date() == start.date()})
    if not conditions:
        raise ValueError('no_session_conditions')
    fields, guard = load_owner_credentials()  # L2-only selection: no private key or signing SDK
    if fields['FUNDER_ADDRESS'].lower() != maker:
        raise ValueError('rewards_account_changed')
    journal = ReadJournal(guard, clock)
    client = AccrualClient(AccrualTransport(fields, guard, journal), args.signature_type)
    record_rewards(root, args.date, maker=maker, conditions=conditions,
                   venue=SimpleNamespace(client=client), journal=journal, clock=clock)
    return 0
