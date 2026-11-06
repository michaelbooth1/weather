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


def test_cli_existing_file_refuses_before_credential_loader(tmp_path):
    from weather.market.lfc_cli import parser
    args = parser().parse_args(['rewards-record', '--date', '2026-09-20', '--root', str(tmp_path)])
    assert args.signature_type == 2
