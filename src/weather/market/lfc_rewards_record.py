"""Owner-run D+1/D+2 incentive evidence, with read-only L2 and public v2 activity.

No private key, signing client, scheduler, order or cancellation capability.
Activity rows are cash candidates, never proof that rewards were earned on D.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
from types import SimpleNamespace

from weather.market.lfc_settlement_record import condition_id, envelope, public_get, response_bytes, retained
from weather.market.mm_stage2_hold import utc, write_new
from weather.market.re1_payout_evidence import ReadJournal, collect_accruals, normalize_earnings
from weather.market.wallet_reader_security import CLOB
from weather.market.wallet_reader_transport import ReadTransport

REWARDS_SCHEMA = 'lfc_rewards_record_v0.1'
REBATE_SCHEMA = 'lfc_rebate_record_v0.1'
MAX_PAGES = 50
MAX_ROWS = 2048
MAX_ACTIVITY_BYTES = 4_000_000
MAX_RECORD_BYTES = 32_000_000


def clob_earnings(rows, *, total=False):
    """Use the pinned SDK models' decimal/date normalization, without a signing client."""
    from polymarket.models.clob.rewards import UserEarning, TotalUserEarning
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise ValueError('earnings_rows')
    model = TotalUserEarning if total else UserEarning
    return [model.model_validate(row).model_dump(mode='json', by_alias=False) for row in rows]


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
        self.journal.record('sdk_response' if raw is not None else 'read_attempt', method='GET', path=path, status=status,
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
            yield SimpleNamespace(items=clob_earnings(page['data']), has_more=more, next_cursor=cursor if more else None)
            if not more:
                return
            seen.add(cursor)
            params['next_cursor'] = cursor
        raise ValueError('earnings_page_budget')

    def get_total_earnings_for_user_for_day(self, *, date):
        rows = self.transport.request('GET', CLOB, '/rewards/user/total',
                                      {'date': date, 'signature_type': self.signature_type})
        return clob_earnings(rows, total=True)


class ActivityReadFailed(ValueError):
    """A refused walk still carries the raw prefix already observed."""
    def __init__(self, reason, rows, pages):
        super().__init__(reason)
        self.evidence = {'pagination_complete': False, 'failure_type': reason, 'payment_verified': False,
                         'pages': pages, **({'partial_rows': rows} if rows else {})}


def read_activity(maker, kind, start, end, *, get=public_get):
    rows, pages = [], []
    try:
        return activity_pages(maker, kind, start, end, rows, pages, get=get)
    except Exception as exc:
        # Reason strings are fixed codes only; raw network exceptions are never echoed.
        reason = str(exc) if isinstance(exc, ValueError) and re.fullmatch(r'activity_[a-z_]+', str(exc)) else type(exc).__name__
        raise ActivityReadFailed(reason, rows, pages) from None


def activity_pages(maker, kind, start, end, rows, pages, *, get):
    """Bounded cursor walk of official v2 Activity; retain every raw envelope."""
    if not re.fullmatch(r'0x[0-9a-f]{40}', maker) or kind not in {'REWARD', 'MAKER_REBATE'}:
        raise ValueError('activity_scope')
    seen, byte_count = set(), 0
    params = {'user': maker, 'type': kind, 'start': int(start.timestamp()) + bool(start.microsecond),
              'end': int(end.timestamp()) - (not end.microsecond), 'limit': 100, 'sort_direction': 'ASC'}
    if end <= start:
        raise ValueError('activity_window_not_open')
    for _ in range(MAX_PAGES):
        raw = get('/v2/activity', params.copy())
        pages.append(retained(raw))
        byte_count += len(raw)
        if byte_count > MAX_ACTIVITY_BYTES:
            raise ValueError('activity_byte_budget')
        page = envelope(raw)
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
        if cursor is not None and not isinstance(cursor, str):
            raise ValueError('activity_pagination')
        cursor = cursor or None
        if pagination['has_more'] != (cursor is not None):
            raise ValueError('activity_pagination')
        if cursor is None:
            return {'rows': rows, 'pages': pages, 'pagination_complete': True,
                    'earned_period_verified': False, 'payment_verified': False,
                    'request_scope': {'user': maker, 'type': kind, 'start': params['start'], 'end': params['end']}}
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


def rebate_path(root, day, lag):
    # Preserve the design's first-pass name and keep D+2 create-only as well.
    suffix = '-rebate' if lag == 1 else '-d2-rebate'
    return Path(root) / 'rewards' / f'{day}{suffix}.json'


def record_rebates(root, day, *, maker, conditions, clock, get=public_get, as_of=None):
    start, cutoff, lag = recording_period(day, as_of or clock())
    target = rebate_path(root, day, lag)
    if target.exists():
        raise FileExistsError('rebate_record_exists')
    try:
        evidence = read_activity(maker, 'MAKER_REBATE', start, cutoff, get=get)
    except Exception as exc:
        evidence = (exc.evidence if isinstance(exc, ActivityReadFailed) else
                    {'pagination_complete': False, 'failure_type': type(exc).__name__, 'payment_verified': False})
    flags = rebate_flags(evidence, conditions)
    row = {'schema_version': REBATE_SCHEMA, 'kind': 'lfc_rebate_record', 'date': day, 'pass': lag,
           'observed_at_utc': utc(clock()).isoformat(), 'query_end_utc': cutoff.isoformat(),
           'maker_address': maker, 'conditions': sorted(set(conditions)),
           'activity': evidence, 'flags': flags, 'netted_against_loss': False,
           'earned_period_verified': False}
    write_new(target, row)
    return row


def rebate_flags(evidence, conditions):
    flags = [] if evidence['pagination_complete'] else [{'flag': 'rebate_read_incomplete'}]
    for index, row in enumerate(evidence.get('rows', evidence.get('partial_rows', []))):
        value = row.get('usdc_size')
        try:
            if isinstance(value, bool):
                raise ValueError
            amount = Decimal(str(value))
            if not amount.is_finite():
                raise ValueError
        except (ValueError, InvalidOperation):
            flags.append({'row': index, 'flag': 'rebate_amount_unreadable'})
            continue
        if amount != 0:
            flags.append({'row': index, 'flag': 'nonzero_maker_rebate', 'amount': str(amount),
                          'pilot_condition': row.get('condition_id') in conditions})
    return flags


def record_rewards(root, day, *, maker, conditions, venue, journal, clock, get=public_get, as_of=None):
    start, cutoff, lag = recording_period(day, as_of or clock())
    target = Path(root) / 'rewards' / f'{day}-d{lag}.json'
    if target.exists():
        raise FileExistsError('rewards_record_exists')
    conditions = sorted({condition_id(c) for c in conditions})
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
        distributions = read_activity(maker, 'REWARD', end, cutoff, get=get)
    except Exception as exc:
        distributions = (exc.evidence if isinstance(exc, ActivityReadFailed) else
                         {'pagination_complete': False, 'failure_type': type(exc).__name__, 'payment_verified': False})
    row = {'schema_version': REWARDS_SCHEMA, 'kind': 'lfc_rewards_record', 'date': day, 'pass': lag,
           'observed_at_utc': utc(clock()).isoformat(), 'query_end_utc': cutoff.isoformat(),
           'maker_address': maker, 'conditions': conditions,
           'accruals': accruals, 'distributions': distributions, 'payment_verified': False,
           'wire_journal': journal.records}
    write_new(target, row)
    return row


def load_record(path, *, kind, day, maker, conditions, lag):
    """A resumed pass must have intact receipts and consistent scope/derived accruals."""
    with Path(path).open('rb') as handle:
        raw = handle.read(MAX_RECORD_BYTES + 1)
    if len(raw) > MAX_RECORD_BYTES:
        raise ValueError('recording_file_budget')
    row = json.loads(raw)
    schema = REWARDS_SCHEMA if kind == 'lfc_rewards_record' else REBATE_SCHEMA
    if (row.get('schema_version') != schema or row.get('kind') != kind or row.get('maker_address') != maker or
            row.get('date') != day or type(row.get('pass')) is not int or row['pass'] != lag or
            row.get('conditions') != conditions):
        raise ValueError('recording_record_scope')
    start, cutoff, actual_lag = recording_period(day, row['query_end_utc'])
    if actual_lag != lag or cutoff > utc(row['observed_at_utc']):
        raise ValueError('recording_record_time')
    activity = row['distributions'] if kind == 'lfc_rewards_record' else row['activity']
    if type(activity.get('pagination_complete')) is not bool or activity.get('payment_verified') is not False:
        raise ValueError('recording_activity_shape')
    for receipt in activity.get('pages', []):
        response_bytes(receipt)
    if activity['pagination_complete'] and not activity.get('pages'):
        raise ValueError('recording_activity_receipts_missing')
    if activity['pagination_complete']:
        pages = iter(activity['pages'])
        replayed = read_activity(maker, 'REWARD' if kind == 'lfc_rewards_record' else 'MAKER_REBATE',
            start + timedelta(days=1) if kind == 'lfc_rewards_record' else start, cutoff,
            get=lambda path, params: response_bytes(next(pages)))
        if replayed != activity or next(pages, None) is not None:
            raise ValueError('recording_activity_mismatch')
    if kind == 'lfc_rebate_record':
        if row.get('netted_against_loss') is not False or row.get('earned_period_verified') is not False:
            raise ValueError('recording_rebate_netted')
        if row.get('flags') != rebate_flags(activity, conditions):
            raise ValueError('recording_rebate_flags')
        return row
    if row.get('payment_verified') is not False or [a['condition_id'] for a in row['accruals']] != conditions:
        raise ValueError('recording_accrual_scope')
    journal = row['wire_journal']
    replies = [r for r in journal if r.get('event') == 'sdk_response' and 'raw_response' in r]
    for reply in replies:
        response_bytes(reply)
    hashes = {r['sha256'] for r in replies if r.get('status') == 200}
    earnings = [r for reply in replies if reply.get('status') == 200 and reply.get('path') == '/rewards/user'
                for r in clob_earnings(envelope(response_bytes(reply))['data'])]
    totals = [clob_earnings(json.loads(response_bytes(reply)), total=True) for reply in replies
              if reply.get('status') == 200 and reply.get('path') == '/rewards/user/total']
    for entry in row['accruals']:
        source = entry['source']
        if type(source.get('complete')) is not bool:
            raise ValueError('recording_accrual_shape')
        if not source['complete']:
            continue
        saved = entry['retained']
        if (source.get('status') != 'OBSERVED' or source.get('pagination_complete') is not True or
                saved['total_earnings'] not in totals or any(r not in earnings for r in saved['rows'])):
            raise ValueError('recording_accrual_receipts_missing')
        scope = dict(maker_address=maker, condition_id=entry['condition_id'],
                     accrual_start_utc=start.isoformat(), accrual_end_utc=(start + timedelta(days=1)).isoformat())
        normalized, all_assets = normalize_earnings([(r, 'probe') for r in saved['rows']],
            [(r, 'probe') for r in saved['total_earnings']], scope, utc(source['observed_at_utc']))
        strip = lambda rows: [{k: v for k, v in r.items() if k not in {'source_record_sha256', 'observed_at_utc'}} for r in rows]
        if (not all_assets or utc(source['observed_at_utc']) < start + timedelta(days=1) or
                strip(normalized) != strip(entry['accruals']) or
                any(r['source_record_sha256'] not in hashes for r in entry['accruals'])):
            raise ValueError('recording_accrual_mismatch')
    return row


def run_rewards_record(args):
    """Owner invocation only. The agent never calls this during implementation or verification."""
    from weather.market.lfc_ledger import Ledger, ledger_path
    from weather.market.lfc_pilot import pilot_root
    from weather.market.wallet_reader_security import load_owner_credentials
    root = args.root or pilot_root()
    clock = lambda: datetime.now(timezone.utc)
    start, observed, lag = recording_period(args.date, clock())
    rewards_path = Path(root) / 'rewards' / f'{args.date}-d{lag}.json'
    rebate_target = rebate_path(root, args.date, lag)
    if rewards_path.exists() and rebate_target.exists():
        raise FileExistsError('rewards_record_exists')
    ledger = Ledger.open(ledger_path(root), clock=clock)
    maker = ledger.rows[0]['maker_address'].lower()
    conditions = sorted({condition_id(s['start']['condition_id']) for s in ledger.sessions.values()
                         if s['legs'] and utc(s['start']['recorded_at_utc']).date() == start.date()})
    if not conditions:
        raise ValueError('no_session_conditions')
    reward = (load_record(rewards_path, kind='lfc_rewards_record', day=args.date, maker=maker,
                          conditions=conditions, lag=lag) if rewards_path.exists() else None)
    rebate = (load_record(rebate_target, kind='lfc_rebate_record', day=args.date, maker=maker,
                          conditions=conditions, lag=lag) if rebate_target.exists() else None)
    cutoff = utc((reward or rebate)['query_end_utc']) if reward or rebate else observed
    if reward is None:
        fields, guard = load_owner_credentials()  # L2-only selection: no private key or signing SDK
        if fields['FUNDER_ADDRESS'].lower() != maker:
            raise ValueError('rewards_account_changed')
        journal = ReadJournal(guard, clock)
        client = AccrualClient(AccrualTransport(fields, guard, journal), args.signature_type)
        reward = record_rewards(root, args.date, maker=maker, conditions=conditions,
                                venue=SimpleNamespace(client=client), journal=journal, clock=clock, as_of=cutoff)
    if rebate is None:
        rebate = record_rebates(root, args.date, maker=maker, conditions=conditions, clock=clock, as_of=cutoff)
    complete = (reward['distributions']['pagination_complete'] and
                all(a['source']['complete'] for a in reward['accruals']) and rebate['activity']['pagination_complete'])
    print(json.dumps({'rewards_record': str(rewards_path), 'rebate_record': str(rebate_target),
                      'complete': complete, 'rebate_flags': rebate['flags']}))
    return 0 if complete else 2
