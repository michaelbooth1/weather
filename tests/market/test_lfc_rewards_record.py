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
            journal.record('sdk_response', path=path, **retained(json.dumps(result).encode()))
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


def test_interrupted_pass_finishes_rebate_without_loading_credentials(tmp_path, monkeypatch):
    from weather.market.lfc_cli import parser
    from weather.market.lfc_ledger import Ledger
    from weather.market import wallet_reader_security
    now = START + timedelta(days=1, hours=2)
    class FrozenDatetime:
        @staticmethod
        def now(zone):
            return now
    monkeypatch.setattr(recorder, 'datetime', FrozenDatetime)
    monkeypatch.setattr(wallet_reader_security, 'load_owner_credentials',
                        lambda: pytest.fail('credentials must not load on public-only resume'))
    ledger = Ledger.create(tmp_path / 'ledger.jsonl', clock=lambda: START, maker_address=MAKER)
    ledger.record('session_start', session_id='one', counted=True, condition_id=CONDITION)
    ledger.intent(session_id='one', intent_key='one:0', token_id='111', condition_id=CONDITION,
                  price='.4', size='20', fee_rate_bps='0')
    rewards = tmp_path / 'rewards'
    rewards.mkdir()
    (rewards / '2026-09-20-d1.json').write_text(json.dumps(dict(schema_version=recorder.REWARDS_SCHEMA,
        maker_address=MAKER, date='2026-09-20', conditions=[CONDITION], **{'pass': 1},
        distributions={'pagination_complete': True}, accruals=[{'source': {'complete': True}}])))
    original = recorder.record_rebates
    monkeypatch.setattr(recorder, 'record_rebates', lambda *a, **kwargs: original(*a, **kwargs, get=lambda *a: page()))
    args = parser().parse_args(['rewards-record', '--date', '2026-09-20', '--root', str(tmp_path)])
    assert recorder.run_rewards_record(args) == 0
    assert (rewards / '2026-09-20-rebate.json').exists()
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
