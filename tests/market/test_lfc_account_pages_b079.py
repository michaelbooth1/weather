"""Offline venue page sizes and bounded account history.

Guards: B079 accepts the observed 5000-limit envelope and full SDK-shaped trade
pages without weakening completeness, cursor, row or streaming byte bounds.
"""
import json
from types import SimpleNamespace

import httpx
import pytest

from tests.market.test_lfc_unattended_account_reads import sdk_client
from weather.market import mm_account_reads as reads
from weather.market.mm_official_adapter import plain_sdk_value
from weather.market.re1_transport import OwnerVenue


def trade_row(index):
    # Public installed SDK ClobTrade/MakerOrder wire aliases; synthetic identities.
    # Two maker allocations also cover a larger row than a single-maker fill.
    token = str(2**255 + index)
    return dict(id=f'00000000-0000-4000-8000-{index:012d}', market='0x' + 'b' * 64,
        asset_id=token, owner='00000000-0000-4000-8000-000000000000', maker_address='0x' + 'a' * 40,
        taker_order_id='0x' + f'{index:064x}', side='BUY', trader_side='MAKER', price='0.480000',
        size='20.000000', outcome='Yes', status='MINED', fee_rate_bps='0', bucket_index=0,
        transaction_hash='0x' + 'c' * 64, match_time='1794272400', last_update='1794272401',
        maker_orders=[dict(order_id='0x' + f'{index * 2 + n:064x}', asset_id=token,
            maker_address='0x' + 'a' * 40, owner='00000000-0000-4000-8000-000000000000',
            side='BUY', price='0.480000', matched_amount='10.000000', outcome='Yes',
            fee_rate_bps=None) for n in range(2)])


def test_observed_empty_orders_page_is_accepted_by_real_sdk():
    body = {'data': [], 'next_cursor': 'LTE=', 'limit': 5000, 'count': 0}
    _, adapter, http, calls = sdk_client(lambda _: body)
    try:
        assert adapter.open_orders() == []
        assert len(calls) == 1 and calls[0].url.path == '/data/orders'
    finally:
        http.close()


@pytest.mark.parametrize('change', [dict(limit=10001), dict(limit=0), dict(limit=True),
    dict(count=1), dict(count=False), dict(data={}), dict(next_cursor=''), dict(next_cursor=None),
    dict(data=[{}, {}], count=2, limit=1)])
def test_incomplete_or_excessive_envelope_still_refuses(change):
    body = dict(data=[], next_cursor='LTE=', limit=5000, count=0)
    body.update(change)
    with pytest.raises(reads.AmbiguousAccountRead, match='incomplete_account_page'):
        reads.validate_account_page(body)


def test_largest_allowed_limit_is_accepted():
    reads.validate_account_page(dict(data=[], next_cursor='LTE=', limit=10000, count=0))


@pytest.mark.parametrize('count', [5000, 10000])
def test_full_trade_page_through_runtime_reader_and_real_sdk(count, record_testsuite_property):
    body = dict(data=[trade_row(n) for n in range(count)], next_cursor='LTE=', limit=count, count=count)
    length = len(json.dumps(body).encode())
    record_testsuite_property(f'full_{count}_page_spaced_bytes', length)
    record_testsuite_property(f'full_{count}_page_wire_bytes', len(httpx.Response(200, json=body).content))
    assert length > 2_000_000  # The former byte budget rejects an ordinary complete page.
    client, _, http, calls = sdk_client(lambda _: body)
    venue = object.__new__(OwnerVenue)
    venue.client, venue.condition = client, None
    venue.trades_after, venue.trades_seconds = '1791583200', 60
    try:
        rows = venue.trades()
        assert len(rows) == count and rows[-1]['id'].endswith(f'{count - 1:012d}')
        assert len(rows[0]['maker_orders']) == 2
        assert len(calls) == 1 and calls[0].url.path == '/data/trades'
        assert dict(calls[0].url.params) == {'after': '1791583200'}
    finally:
        http.close()


@pytest.mark.parametrize('kind', ['rows', 'pages', 'cursor'])
def test_large_history_never_silently_truncates(kind):
    def page(items, cursor):
        return SimpleNamespace(items=items, next_cursor=cursor, has_more=cursor is not None)
    if kind == 'rows':
        pages = [page([{'id': str(n)}] * 5000, str(n)) for n in range(5)]
        assert len(reads.account_rows(pages[:-1] + [page(pages[-1].items, None)],
                                     normalize=plain_sdk_value)) == 25000
        pages.append(page([{'id': 'one-too-many'}], None))
        reason = 'account_row_budget'
    elif kind == 'pages':
        pages = [page([], str(n)) for n in range(50)]
        assert reads.account_rows(pages[:-1] + [page([], None)], normalize=plain_sdk_value) == []
        reason = 'account_page_budget'
    else:
        pages = [page([], 'cycle'), page([], 'cycle')]
        reason = 'account_pagination'
    with pytest.raises(reads.AmbiguousAccountRead, match=reason):
        reads.account_rows(pages, normalize=plain_sdk_value)


def test_streaming_byte_budget_still_refuses_before_json_decode():
    cap = getattr(reads, 'ACCOUNT_RESPONSE_MAX_BYTES', 2_000_000)
    seen = []
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(cap // 65536 + 2):
                seen.append(65536)
                yield b' ' * 65536
    response = httpx.Response(200, request=httpx.Request('GET', 'https://clob.polymarket.com/data/trades'),
                              stream=Stream())
    try:
        with pytest.raises(reads.AmbiguousAccountRead, match='account_response_budget'):
            reads.validate_account_response(response)
        assert cap < sum(seen) <= cap + 65536
    finally:
        response.close()


@pytest.mark.parametrize('extra', [0, 1])
def test_streaming_byte_ceiling_is_inclusive(extra):
    cap = getattr(reads, 'ACCOUNT_RESPONSE_MAX_BYTES', 2_000_000)
    prefix = b'{"data":[],"next_cursor":"LTE=","limit":5000,"count":0}'
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            yield prefix
            remaining = cap + extra - len(prefix)
            while remaining:
                size = min(remaining, 65536)
                yield b' ' * size
                remaining -= size
    response = httpx.Response(200, request=httpx.Request('GET', 'https://clob.polymarket.com/data/orders'),
                              stream=Stream())
    try:
        if extra:
            with pytest.raises(reads.AmbiguousAccountRead, match='account_response_budget'):
                reads.validate_account_response(response)
        else:
            reads.validate_account_response(response)
            assert len(response.content) == cap
    finally:
        response.close()


def test_only_attested_session0_identity_is_exempt_from_history_recovery(tmp_path):
    from tests.market.test_lfc_cli import ledger_with_baselines, pass_all_session0, pass_session0
    from weather.market.lfc_campaign_history import history_refusals, qualified_exercises
    ledger = ledger_with_baselines(tmp_path)
    pass_all_session0(ledger, tmp_path)
    qualified = qualified_exercises(ledger, tmp_path)
    attested_0c = next(sid for sid in qualified if ledger.sessions[sid]['start'].get('session0_run') == '0c')
    assert attested_0c not in history_refusals(ledger, tmp_path)
    # A later same-kind exercise is not silently covered by the old attestation.
    pass_session0(ledger, run='0c', reason='reconciled_after_crash')
    later_0c = next(reversed(ledger.sessions))
    assert later_0c != attested_0c
    assert later_0c in history_refusals(ledger, tmp_path)
    assert attested_0c not in history_refusals(ledger, tmp_path)
