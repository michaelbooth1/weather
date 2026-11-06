"""Closed, synthetic CLOB accrual and v2 activity responses only.

Guards: F2 R3 immutable D+1/D+2 reward evidence, cursor bounds and separation of accrual from payment.
"""
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from weather.market import lfc_rewards_record as recorder
from weather.market import re1_transport
from weather.market.re1_attended import SecretGuard
from weather.market.re1_payout_evidence import ASSET_MARKERS, ReadJournal

MAKER = '0x' + 'a' * 40
CONDITION = '0x' + 'c' * 64
START = datetime(2026, 9, 20, tzinfo=timezone.utc)


def activity(kind='REWARD', amount=1.25):
    return dict(proxy_wallet=MAKER, timestamp=int((START + timedelta(days=1, hours=1)).timestamp()),
                condition_id=CONDITION, type=kind, size=amount, usdc_size=amount,
                transaction_hash='0x' + 'f' * 64, token_id='', price=0)


def page(rows=(), cursor=None):
    return json.dumps({'data': list(rows), 'pagination': {'has_more': cursor is not None,
                      'next_cursor': cursor, 'limit': 100, 'offset': 0}}).encode()


def accrual_fixture(monkeypatch):
    clock = lambda: START + timedelta(days=1, hours=2)
    journal = ReadJournal(SecretGuard(), clock)
    assets = list(ASSET_MARKERS)
    earnings = [dict(maker_address=MAKER, condition_id=CONDITION, asset_address=asset,
        date=START.isoformat(), earnings='1.25', asset_rate='1') for asset in assets]
    totals = [{k: v for k, v in row.items() if k != 'condition_id'} for row in earnings]
    class Transport:
        def request(self, method, host, path, params):
            assert method == 'GET' and path in {'/rewards/user', '/rewards/user/total'}
            result = {'data': earnings, 'next_cursor': 'LTE='} if path.endswith('/user') else totals
            from weather.market.lfc_settlement_record import retained
            journal.record('sdk_response', path=path, status=200, **retained(json.dumps(result).encode()))
            return result
    monkeypatch.setattr(re1_transport, 'condition_configurations', lambda condition, journal: [])
    return SimpleNamespace(client=recorder.AccrualClient(Transport(), 2)), journal, clock


def test_d1_d2_keep_accrual_separate_from_paid_and_refuse_overwrite(tmp_path, monkeypatch):
    venue, journal, clock = accrual_fixture(monkeypatch)
    calls = []
    def get(path, params):
        calls.append((path, params))
        return page([activity()], 'next') if 'cursor' not in params else page()
    row = recorder.record_rewards(tmp_path, '2026-09-20', maker=MAKER, conditions=[CONDITION],
                                  venue=venue, journal=journal, clock=clock, get=get)
    assert row['accruals'][0]['source']['complete'] is True
    assert row['accruals'][0]['accruals'][0]['status'] == 'ACCRUED'
    assert row['distributions']['pagination_complete'] is True
    assert row['distributions']['rows'][0]['usdc_size'] == 1.25
    assert row['distributions']['payment_verified'] is False and row['payment_verified'] is False
    assert calls[0][1]['sort_direction'] == 'ASC' and calls[1][1]['cursor'] == 'next'
    target = tmp_path / 'rewards' / '2026-09-20-d1.json'
    before = target.read_bytes()
    with pytest.raises(FileExistsError):
        recorder.record_rewards(tmp_path, '2026-09-20', maker=MAKER, conditions=[CONDITION],
            venue=None, journal=None, clock=clock, get=lambda *a: pytest.fail('overwrite GET'))
    assert target.read_bytes() == before
    recorder.record_rewards(tmp_path, '2026-09-20', maker=MAKER, conditions=[CONDITION], venue=venue,
        journal=journal, clock=lambda: START + timedelta(days=2, hours=2), get=lambda *a: page())
    assert (tmp_path / 'rewards' / '2026-09-20-d2.json').exists()


@pytest.mark.parametrize('lag', [0, 3, -1])
def test_outside_recording_window_refused(lag):
    with pytest.raises(ValueError, match='rewards_record_only_d1_d2'):
        recorder.recording_period('2026-09-20', START + timedelta(days=lag))


@pytest.mark.parametrize('reply,reason', [
    (page([dict(activity(), proxy_wallet='0x' + 'b' * 40)]), 'activity_row_scope'),
    (page([dict(activity(), type='TRADE')]), 'activity_row_scope'),
    (page([dict(activity(), timestamp=1)]), 'activity_row_scope'),
    (b'{"data":[]}', 'activity_pagination'),
    (b'{"data":[],"pagination":{"has_more":false,"next_cursor":"next"}}', 'activity_pagination'),
])
def test_activity_scope_and_pagination_fail_closed(reply, reason):
    with pytest.raises(ValueError, match=reason):
        recorder.read_activity(MAKER, 'REWARD', START, START + timedelta(days=2), get=lambda *a: reply)


def test_activity_cursor_cycle_and_budget(monkeypatch):
    with pytest.raises(ValueError, match='activity_cursor'):
        recorder.read_activity(MAKER, 'REWARD', START, START + timedelta(days=2), get=lambda *a: page(cursor='same'))
    monkeypatch.setattr(recorder, 'MAX_PAGES', 1)
    with pytest.raises(ValueError, match='activity_page_budget'):
        recorder.read_activity(MAKER, 'REWARD', START, START + timedelta(days=2), get=lambda *a: page(cursor='next'))


def test_failed_reads_retained_as_failure_not_zero(tmp_path, monkeypatch):
    venue, journal, clock = accrual_fixture(monkeypatch)
    venue.client.get_total_earnings_for_user_for_day = lambda **kwargs: (_ for _ in ()).throw(TimeoutError())
    def fail(*a):
        raise TimeoutError()
    row = recorder.record_rewards(tmp_path, '2026-09-20', maker=MAKER, conditions=[CONDITION], venue=venue,
                                  journal=journal, clock=clock, get=fail)
    assert row['accruals'][0]['source']['status'] == 'FAILED'
    assert row['distributions']['pagination_complete'] is False
    assert 'rows' not in row['distributions'] and row['payment_verified'] is False


def test_cli_parser_selects_readonly_recorder(tmp_path):
    from weather.market.lfc_cli import parser
    args = parser().parse_args(['rewards-record', '--date', '2026-09-20', '--root', str(tmp_path)])
    assert args.signature_type == 2


def test_rebates_flagged_never_netted_and_both_passes_immutable(tmp_path):
    calls = []
    def get(path, params):
        calls.append((path, params))
        return page([activity('MAKER_REBATE', 2), activity('MAKER_REBATE', 0)])
    row = recorder.record_rebates(tmp_path, '2026-09-20', maker=MAKER, conditions=[CONDITION],
        clock=lambda: START + timedelta(days=1, hours=2), get=get)
    assert row['activity']['rows'][0]['usdc_size'] == 2
    assert row['flags'] == [{'row': 0, 'flag': 'nonzero_maker_rebate', 'amount': '2', 'pilot_condition': True}]
    assert row['netted_against_loss'] is False and row['earned_period_verified'] is False
    assert calls[0][1]['type'] == 'MAKER_REBATE' and calls[0][1]['start'] == int(START.timestamp())
    target = tmp_path / 'rewards' / '2026-09-20-rebate.json'
    before = target.read_bytes()
    with pytest.raises(FileExistsError):
        recorder.record_rebates(tmp_path, '2026-09-20', maker=MAKER, conditions=[CONDITION],
            clock=lambda: START + timedelta(days=1, hours=2), get=lambda *a: pytest.fail('overwrite GET'))
    assert target.read_bytes() == before
    recorder.record_rebates(tmp_path, '2026-09-20', maker=MAKER, conditions=[CONDITION],
        clock=lambda: START + timedelta(days=2, hours=2), get=get)
    assert (tmp_path / 'rewards' / '2026-09-20-d2-rebate.json').exists()


@pytest.mark.parametrize('amount', ['NaN', 'Infinity', None, True])
def test_unreadable_rebate_amount_flagged(tmp_path, amount):
    row = recorder.record_rebates(tmp_path, '2026-09-20', maker=MAKER, conditions=[CONDITION],
        clock=lambda: START + timedelta(days=1, hours=2), get=lambda *a: page([activity('MAKER_REBATE', amount)]))
    assert row['flags'] == [{'row': 0, 'flag': 'rebate_amount_unreadable'}]
    assert row['netted_against_loss'] is False


def test_zero_rebate_is_observed_not_reward_credit(tmp_path):
    row = recorder.record_rebates(tmp_path, '2026-09-20', maker=MAKER, conditions=[CONDITION],
        clock=lambda: START + timedelta(days=1, hours=2), get=lambda *a: page())
    assert row['flags'] == [] and row['activity']['rows'] == []
    assert row['activity']['pagination_complete'] is True and row['netted_against_loss'] is False


def test_partial_activity_failure_preserves_raw_prefix_and_flags_rebate(tmp_path):
    def get(path, params):
        if 'cursor' in params:
            raise TimeoutError()
        return page([activity('MAKER_REBATE', 2)], 'next')
    row = recorder.record_rebates(tmp_path, '2026-09-20', maker=MAKER, conditions=[CONDITION],
        clock=lambda: START + timedelta(days=1, hours=2), get=get)
    assert row['activity']['pagination_complete'] is False
    assert len(row['activity']['pages']) == 1 and len(row['activity']['partial_rows']) == 1
    assert {f['flag'] for f in row['flags']} == {'rebate_read_incomplete', 'nonzero_maker_rebate'}


@pytest.mark.parametrize('resume_lag', [1, 2, 3])
def test_interrupted_pass_finishes_rebate_without_loading_credentials(tmp_path, monkeypatch, resume_lag):
    from weather.market.lfc_cli import parser
    from weather.market.lfc_ledger import Ledger
    now = START + timedelta(days=resume_lag, hours=2)
    class FrozenDatetime:
        @staticmethod
        def now(zone):
            return now
    monkeypatch.setattr(recorder, 'datetime', FrozenDatetime)
    monkeypatch.setattr(recorder, 'load_reward_credentials',
                        lambda: pytest.fail('credentials must not load on public-only resume'))
    ledger = Ledger.create(tmp_path / 'ledger.jsonl', clock=lambda: START, maker_address=MAKER)
    ledger.record('session_start', session_id='one', counted=True, condition_id=CONDITION)
    ledger.intent(session_id='one', intent_key='one:0', token_id='111', condition_id=CONDITION,
                  price='.4', size='20', fee_rate_bps='0')
    venue, journal, clock = accrual_fixture(monkeypatch)
    recorder.record_rewards(tmp_path, '2026-09-20', maker=MAKER, conditions=[CONDITION],
                            venue=venue, journal=journal, clock=clock, get=lambda *a: page())
    rewards = tmp_path / 'rewards'
    original = recorder.record_rebates
    monkeypatch.setattr(recorder, 'record_rebates', lambda *a, **kwargs: original(*a, **kwargs, get=lambda *a: page()))
    args = parser().parse_args(['rewards-record', '--date', '2026-09-20', '--root', str(tmp_path)])
    assert recorder.run_rewards_record(args) == 0
    assert (rewards / '2026-09-20-rebate.json').exists()
    assert not (rewards / '2026-09-20-d2-rebate.json').exists()
    if resume_lag == 1:
        with pytest.raises(FileExistsError):
            recorder.run_rewards_record(args)


def test_accrual_transport_get_only_and_retains_exact_raw_response(tmp_path):
    import hashlib
    from io import BytesIO
    from weather.market.wallet_reader_security import CLOB
    raw = b'{"data": [], "next_cursor": "LTE="}\n'
    requests = []
    class Reply(BytesIO):
        status = 200
        def geturl(self):
            return requests[-1].full_url
    class ClosedOpener:
        def open(self, request, timeout):
            assert request.get_method() == 'GET' and request.data is None
            requests.append(request)
            return Reply(raw)
    fields = dict(WALLET_ADDRESS=MAKER, FUNDER_ADDRESS=MAKER, API_KEY='synthetic-key',
                  API_SECRET='c3ludGhldGlj', API_PASSPHRASE='synthetic-passphrase')
    journal = ReadJournal(SecretGuard(), lambda: START)
    transport = recorder.AccrualTransport(fields, SecretGuard(), journal, opener=ClosedOpener(), journal_root=tmp_path)
    client = recorder.AccrualClient(transport, 2)
    pages = list(client.list_user_earnings_for_day(date='2026-09-20'))
    assert len(pages) == 1 and pages[0].items == [] and pages[0].has_more is False
    retained = [r for r in journal.records if r['event'] == 'sdk_response'][0]
    assert retained['raw_response'].encode() == raw and retained['sha256'] == hashlib.sha256(raw).hexdigest()
    for method, path in [('POST', '/rewards/user'), ('GET', '/balance-allowance/update'), ('GET', '/data/orders')]:
        with pytest.raises(ValueError, match='accrual_endpoint_refused'):
            transport.request(method, CLOB, path)
    assert len(requests) == 1


def test_activity_partial_second_and_empty_terminal_cursor():
    start = START + timedelta(microseconds=250_000)
    end = START + timedelta(days=2, microseconds=500_000)
    calls = []
    def get(path, params):
        calls.append(params)
        return json.dumps({'data': [dict(activity(), timestamp=int(end.timestamp()))],
                           'pagination': {'has_more': False, 'next_cursor': ''}}).encode()
    row = recorder.read_activity(MAKER, 'REWARD', start, end, get=get)
    assert row['pagination_complete'] is True and len(row['rows']) == 1
    assert calls[0]['start'] == int(START.timestamp()) + 1
    assert calls[0]['end'] == int(end.timestamp())
    with pytest.raises(ValueError, match='activity_pagination'):
        recorder.read_activity(MAKER, 'REWARD', START, end,
            get=lambda *a: b'{"data":[],"pagination":{"has_more":false,"next_cursor":false}}')


def test_midnight_does_not_split_pass_files(tmp_path, monkeypatch):
    venue, journal, _ = accrual_fixture(monkeypatch)
    cutoff = START + timedelta(days=2, microseconds=-100_000)
    clock = lambda: START + timedelta(days=2, seconds=1)
    reward = recorder.record_rewards(tmp_path, '2026-09-20', maker=MAKER, conditions=[CONDITION],
        venue=venue, journal=journal, clock=clock, as_of=cutoff, get=lambda *a: page())
    rebate = recorder.record_rebates(tmp_path, '2026-09-20', maker=MAKER, conditions=[CONDITION],
        clock=clock, as_of=cutoff, get=lambda *a: page())
    assert reward['pass'] == rebate['pass'] == 1
    assert reward['query_end_utc'] == rebate['query_end_utc'] == cutoff.isoformat()
    assert reward['observed_at_utc'] == rebate['observed_at_utc'] == clock().isoformat()
    assert (tmp_path / 'rewards' / '2026-09-20-d1.json').exists()
    assert (tmp_path / 'rewards' / '2026-09-20-rebate.json').exists()
    assert not (tmp_path / 'rewards' / '2026-09-20-d2-rebate.json').exists()


@pytest.mark.parametrize('mutation,reason', [('receipt', 'recording_response_hash'),
                                           ('amount', 'recording_accrual_mismatch'),
                                           ('activity', 'recording_activity_mismatch')])
def test_resume_rejects_corrupt_receipt_or_derived_values(tmp_path, monkeypatch, mutation, reason):
    venue, journal, clock = accrual_fixture(monkeypatch)
    row = recorder.record_rewards(tmp_path, '2026-09-20', maker=MAKER, conditions=[CONDITION],
        venue=venue, journal=journal, clock=clock, get=lambda *a: page())
    path = tmp_path / 'rewards' / '2026-09-20-d1.json'
    assert recorder.load_record(path, kind='lfc_rewards_record', day='2026-09-20', maker=MAKER,
                                conditions=[CONDITION], lag=1) == row
    if mutation == 'receipt':
        row['wire_journal'][0]['raw_response'] += ' '
    elif mutation == 'amount':
        row['accruals'][0]['accruals'][0]['amount'] = '999'
    else:
        row['distributions']['rows'] = [activity()]
    path.write_text(json.dumps(row))
    with pytest.raises(ValueError, match=reason):
        recorder.load_record(path, kind='lfc_rewards_record', day='2026-09-20', maker=MAKER,
                             conditions=[CONDITION], lag=1)


def test_resume_rejects_removed_nonzero_rebate_flag(tmp_path):
    row = recorder.record_rebates(tmp_path, '2026-09-20', maker=MAKER, conditions=[CONDITION],
        clock=lambda: START + timedelta(days=1, hours=2), get=lambda *a: page([activity('MAKER_REBATE', 2)]))
    path = tmp_path / 'rewards' / '2026-09-20-rebate.json'
    row['flags'] = []
    path.write_text(json.dumps(row))
    with pytest.raises(ValueError, match='recording_rebate_flags'):
        recorder.load_record(path, kind='lfc_rebate_record', day='2026-09-20', maker=MAKER,
                             conditions=[CONDITION], lag=1)


def test_activity_byte_budget_keeps_raw_prefix(monkeypatch):
    monkeypatch.setattr(recorder, 'MAX_ACTIVITY_BYTES', 1)
    with pytest.raises(recorder.ActivityReadFailed, match='activity_byte_budget') as error:
        recorder.read_activity(MAKER, 'REWARD', START, START + timedelta(days=2), get=lambda *a: page())
    assert len(error.value.evidence['pages']) == 1


def test_absent_asset_totals_are_not_completed_zero(tmp_path, monkeypatch):
    venue, journal, clock = accrual_fixture(monkeypatch)
    venue.client.list_user_earnings_for_day = lambda **kwargs: iter([SimpleNamespace(items=[], has_more=False, next_cursor=None)])
    def totals(**kwargs):
        from weather.market.lfc_settlement_record import retained
        journal.record('sdk_response', path='/rewards/user/total', status=200, **retained(b'[]'))
        return []
    venue.client.get_total_earnings_for_user_for_day = totals
    row = recorder.record_rewards(tmp_path, '2026-09-20', maker=MAKER, conditions=[CONDITION],
        venue=venue, journal=journal, clock=clock, get=lambda *a: page())
    assert row['accruals'][0]['source']['complete'] is False
    assert row['accruals'][0]['source']['reason'] == 'asset_total_missing'
    assert row['accruals'][0]['accruals'] == []


def test_numeric_clob_earnings_use_sdk_decimal_semantics(tmp_path, monkeypatch):
    clock = lambda: START + timedelta(days=1, hours=2)
    journal = ReadJournal(SecretGuard(), clock)
    rows = [dict(asset_address=asset, maker_address=MAKER, asset_rate=1, date=START.isoformat(),
                 condition_id=condition, earnings=value)
            for asset in ASSET_MARKERS for condition, value in ((CONDITION, .1), ('0x' + 'd' * 64, .2))]
    totals = [dict(asset_address=asset, maker_address=MAKER, asset_rate=1, date=START.isoformat(), earnings=.3)
              for asset in ASSET_MARKERS]
    class RawTransport:
        def request(self, method, host, path, params):
            from weather.market.lfc_settlement_record import retained
            payload = {'data': rows, 'next_cursor': 'LTE='} if path == '/rewards/user' else totals
            journal.record('sdk_response', status=200, path=path, **retained(json.dumps(payload).encode()))
            return payload
    monkeypatch.setattr(re1_transport, 'condition_configurations', lambda condition, journal: [])
    row = recorder.record_rewards(tmp_path, '2026-09-20', maker=MAKER, conditions=[CONDITION],
        venue=SimpleNamespace(client=recorder.AccrualClient(RawTransport(), 2)), journal=journal,
        clock=clock, get=lambda *a: page())
    assert row['accruals'][0]['source']['complete'] is True
    assert {r['venue_amount'] for r in row['accruals'][0]['accruals']} == {'0.1', '0.2'}
    assert recorder.load_record(tmp_path / 'rewards' / '2026-09-20-d1.json', kind='lfc_rewards_record',
        day='2026-09-20', maker=MAKER, conditions=[CONDITION], lag=1) == row


def owner_command(tmp_path, monkeypatch, *, session=True, now=None):
    from weather.market.lfc_cli import parser
    from weather.market.lfc_ledger import Ledger
    class FrozenDatetime:
        @staticmethod
        def now(zone):
            return now or START + timedelta(days=1, hours=2)
    monkeypatch.setattr(recorder, 'datetime', FrozenDatetime)
    ledger = Ledger.create(tmp_path / 'ledger.jsonl', clock=lambda: START, maker_address=MAKER)
    if session:
        ledger.record('session_start', session_id='S1', counted=True, condition_id=CONDITION)
        ledger.intent(session_id='S1', intent_key='S1:0', token_id='111', condition_id=CONDITION,
                      price='.4', size='20', fee_rate_bps='0')
    return parser().parse_args(['rewards-record', '--date', '2026-09-20', '--root', str(tmp_path)])


def test_no_session_conditions_before_credentials(tmp_path, monkeypatch):
    args = owner_command(tmp_path, monkeypatch, session=False)
    monkeypatch.setattr(recorder, 'load_reward_credentials', lambda: pytest.fail('must not load credentials'))
    with pytest.raises(ValueError, match='no_session_conditions'):
        recorder.run_rewards_record(args)


def test_rewards_account_changed_before_transport(tmp_path, monkeypatch):
    args = owner_command(tmp_path, monkeypatch)
    monkeypatch.setattr(recorder, 'load_reward_credentials',
                        lambda: ({'FUNDER_ADDRESS': '0x' + 'b' * 40}, SecretGuard()))
    monkeypatch.setattr(recorder, 'AccrualTransport', lambda *a: pytest.fail('must not construct transport'))
    with pytest.raises(ValueError, match='rewards_account_changed'):
        recorder.run_rewards_record(args)


def test_reward_credentials_need_no_reader_token_or_dotenv(monkeypatch):
    from pathlib import Path
    values = dict(API_KEY='synthetic-key', API_SECRET='c3ludGhldGlj', API_PASSPHRASE='synthetic-passphrase',
                  WALLET_ADDRESS='0x' + 'b' * 40, FUNDER_ADDRESS=MAKER)
    requested = []
    class Environment(dict):
        def get(self, key, default=None):
            requested.append(key)
            return super().get(key, default)
    monkeypatch.setattr(recorder.os, 'environ', Environment({'POLYMM_' + k: v for k, v in values.items()}))
    monkeypatch.setattr(Path, 'open', lambda *a, **kw: pytest.fail('credential loader must not open files'))
    fields, guard = recorder.load_reward_credentials()
    assert fields == values
    assert 'POLYMM_READER_TOKEN' not in requested and 'POLYMM_PRIVATE_KEY' not in requested


def test_failed_d1_read_retries_create_only_and_keeps_pass_after_midnight(tmp_path, monkeypatch):
    venue, journal, clock = accrual_fixture(monkeypatch)
    def fail(*a):
        raise TimeoutError()
    initial = recorder.record_rewards(tmp_path, '2026-09-20', maker=MAKER, conditions=[CONDITION],
        venue=venue, journal=journal, clock=clock, get=fail)
    recorder.record_rebates(tmp_path, '2026-09-20', maker=MAKER, conditions=[CONDITION], clock=clock, get=lambda *a: page())
    base = tmp_path / 'rewards' / '2026-09-20-d1.json'
    before = base.read_bytes()
    assert recorder.record_complete(initial) is False
    args = owner_command(tmp_path, monkeypatch, now=START + timedelta(days=2, hours=1))
    monkeypatch.setattr(recorder, 'load_reward_credentials', lambda: ({'FUNDER_ADDRESS': MAKER}, SecretGuard()))
    monkeypatch.setattr(recorder, 'AccrualTransport', lambda *a: None)
    monkeypatch.setattr(recorder, 'AccrualClient', lambda *a: None)
    original = recorder.record_rewards
    def collect(*args, **kwargs):
        kwargs.update(venue=venue, journal=journal, get=lambda *a: page())
        return original(*args, **kwargs)
    monkeypatch.setattr(recorder, 'record_rewards', collect)
    assert recorder.run_rewards_record(args) == 0
    assert base.read_bytes() == before
    retry = tmp_path / 'rewards' / '2026-09-20-d1-retry-001.json'
    row = json.loads(retry.read_bytes())
    assert row['pass'] == 1 and recorder.record_complete(row) is True
    assert not (tmp_path / 'rewards' / '2026-09-20-d2.json').exists()


def test_failed_rebate_can_retry_without_overwriting(tmp_path):
    clock = lambda: START + timedelta(days=1, hours=2)
    def fail(*a):
        raise TimeoutError()
    recorder.record_rebates(tmp_path, '2026-09-20', maker=MAKER, conditions=[CONDITION], clock=clock, get=fail)
    base = tmp_path / 'rewards' / '2026-09-20-rebate.json'
    before = base.read_bytes()
    row = recorder.record_rebates(tmp_path, '2026-09-20', maker=MAKER, conditions=[CONDITION], clock=clock, get=lambda *a: page())
    assert recorder.record_complete(row) is True and base.read_bytes() == before
    assert (tmp_path / 'rewards' / '2026-09-20-rebate-retry-001.json').exists()


def test_recorded_activity_empty_page_shape():
    from pathlib import Path
    raw = (Path(__file__).resolve().parents[1] / 'fixtures' / 'lfc_recording' /
           'public_v2_20261106' / 'activity.json').read_bytes()
    row = recorder.read_activity(MAKER, 'REWARD', START, START + timedelta(days=1), get=lambda *a: raw)
    assert row['rows'] == [] and row['pagination_complete'] is True
