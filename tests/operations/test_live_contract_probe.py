from io import BytesIO
import json
from types import SimpleNamespace
from urllib.request import Request

import pytest

from weather.operations import live_contract_probe as probe
from weather.operations.live_contract_sources import public_definitions


def test_projection_loads_no_order_or_credential_module():
    import sys
    before = set(sys.modules)
    source = public_definitions(lambda *a, **k: pytest.fail('network during source load'))
    new_modules = set(sys.modules) - before
    assert not any(name.startswith(('weather.market.re1_', 'weather.market.mm_official_adapter',
                                     'weather.market.mm_stage2_hold', 'polymarket')) for name in new_modules)
    assert not hasattr(source, 'load_owner_credentials')
    assert not hasattr(source, 'OwnerVenue')
    assert not hasattr(source, 'OfficialPolymarketGlobalAdapter')
    assert set(source.source_sha256) == {'re1_owner_checks', 're1_transport', 'mm_official_adapter',
                                       'mm_stage2_hold', 'mm_stage2_selection'}


class Response(BytesIO):
    status = 200
    headers = {'Content-Type': 'application/json'}
    def __init__(self, payload, url):
        super().__init__(json.dumps(payload).encode())
        self.url = url
    def geturl(self):
        return self.url


def test_one_shot_refuses_repeat_and_unapproved_url(monkeypatch):
    url = 'https://polymarket.com/api/geoblock'
    calls = []
    def open_request(request, **kwargs):
        calls.append(request)
        return Response({}, url)
    monkeypatch.setattr(probe.http, '_OPENER', SimpleNamespace(open=open_request))
    opener = probe.OneShotPublicOpener({('GET', url)})
    opener(Request(url), timeout=2).close()
    with pytest.raises(ValueError, match='one-shot'):
        opener(Request(url), timeout=2)
    with pytest.raises(ValueError, match='one-shot'):
        opener(Request('https://clob.polymarket.com/orders'), timeout=2)
    assert len(calls) == 1


def test_probe_executes_all_five_contracts_and_reports_failure(monkeypatch, capsys):
    token, condition, address = '1001', '0x' + 'a' * 64, '0x' + '1' * 40
    monkeypatch.setattr(probe, 'configured_pair', lambda *args: None)
    # The real definition's clean-Git requirement is tested by the real run;
    # isolate only its external subprocess in this deterministic test.
    import subprocess
    original_run = subprocess.run
    def git(args, **kwargs):
        if args[0] == 'git':
            return SimpleNamespace(stdout='' if 'status' in args else 'a' * 40)
        return original_run(args, **kwargs)
    monkeypatch.setattr(subprocess, 'run', git)
    calls = []
    def open_request(request, **kwargs):
        calls.append(request.full_url)
        if '/api/geoblock' in request.full_url:
            payload = {'blocked': False}
        elif 'polygon' in request.full_url:
            payload = {'jsonrpc': '2.0', 'id': 1, 'result': '0x123'}
        elif '/book?' in request.full_url:
            payload = {'asset_id': token, 'market': condition, 'tick_size': '.01', 'min_order_size': '5',
                       'neg_risk': True, 'bids': [], 'asks': []}
        elif '/rewards/markets/' in request.full_url:
            payload = {'data': [], 'count': 0, 'limit': 100, 'next_cursor': 'LTE='}
        else:
            payload = []
        return Response(payload, request.full_url)
    monkeypatch.setattr(probe.http, '_OPENER', SimpleNamespace(open=open_request))
    assert probe.run(token=token, condition=condition, public_address=address) == 1
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(calls) == 5
    assert [row['status'] for row in rows[:5]] == ['PASS', 'PASS', 'PASS', 'FAIL', 'PASS']


def test_response_wrapper_bounds_unbounded_live_positions_read():
    response = BytesIO(b'x' * 101)
    with pytest.raises(ValueError, match='bound'):
        probe._BoundedResponse(response, limit=100).read()
