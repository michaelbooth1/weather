from io import BytesIO
from http.client import IncompleteRead
import json
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest

from weather import http


class Response(BytesIO):
    status = 200


def opener(monkeypatch, body=b'{"ok":true}', status=200):
    calls = []
    response = Response(body)
    response.status = status
    def open_request(request, **kwargs):
        calls.append((request, kwargs))
        return response
    monkeypatch.setattr(http, '_OPENER', SimpleNamespace(open=open_request))
    monkeypatch.setattr(http, '_short_commit', lambda: '123456789')
    return calls, response


def test_json_headers_body_and_single_bounded_read(monkeypatch):
    calls, response = opener(monkeypatch)
    assert http.json_request('https://example.com', method='POST', body={'id': 1}, timeout=2, max_bytes=100,
                             headers={'User-Agent': http.user_agent('probe')}) == {'ok': True}
    assert len(calls) == 1 and response.closed
    request, kwargs = calls[0]
    assert request.get_header('User-agent') == 'weather/probe/123456789'
    assert request.get_header('Accept') == 'application/json'
    assert json.loads(request.data) == {'id': 1}
    assert kwargs == {'timeout': 2.0}


@pytest.mark.parametrize('body,status,limit,reason', [
    (b'x' * 400, 200, 300, 'too large'),
    (b'not json', 200, 100, 'invalid JSON'),
    (b'\xff', 200, 100, 'invalid JSON'),
    (b'no', 403, 100, 'HTTP failure'),
])
def test_typed_errors_close_response(monkeypatch, body, status, limit, reason):
    calls, response = opener(monkeypatch, body, status)
    with pytest.raises(http.JsonRequestError, match=reason) as caught:
        http.json_request('https://example.com', method='GET', timeout=2, max_bytes=limit)
    assert caught.value.status == status
    assert caught.value.body_preview == body[:limit + 1].decode('utf-8', errors='replace')[:200]
    assert response.closed and len(calls) == 1


def test_http_error_is_bounded_and_not_retried(monkeypatch):
    body = Response(b'x' * 1000)
    error = HTTPError('https://example.com', 403, 'Forbidden', {}, body)
    calls = []
    def fail(*args, **kwargs):
        calls.append(1)
        raise error
    monkeypatch.setattr(http, '_OPENER', SimpleNamespace(open=fail))
    with pytest.raises(http.JsonRequestError) as caught:
        http.json_request('https://example.com', method='GET', timeout=2, max_bytes=1000)
    assert caught.value.status == 403 and caught.value.body_preview == 'x' * 200
    assert body.closed and calls == [1]


def test_transport_failure(monkeypatch):
    def fail(*args, **kwargs):
        raise URLError('offline')
    monkeypatch.setattr(http, '_OPENER', SimpleNamespace(open=fail))
    with pytest.raises(http.JsonRequestError) as caught:
        http.json_request('https://example.com', method='GET', timeout=2, max_bytes=100)
    assert caught.value.status is None


@pytest.mark.parametrize('status', [200, 403])
def test_truncated_body_remains_typed_with_status_and_preview(monkeypatch, status):
    class TruncatedResponse(Response):
        def read(self, size=-1):
            raise IncompleteRead(b'partial response', 30)
    response = TruncatedResponse()
    def open_request(*args, **kwargs):
        if status == 403:
            raise HTTPError('https://example.com', status, 'Forbidden', {}, response)
        return response
    monkeypatch.setattr(http, '_OPENER', SimpleNamespace(open=open_request))
    with pytest.raises(http.JsonRequestError) as caught:
        http.json_request('https://example.com', method='GET', timeout=2, max_bytes=100)
    assert caught.value.status == status
    assert caught.value.body_preview == 'partial response'
    assert response.closed


def test_location_refresh_uses_shared_helper_and_keeps_pagination(monkeypatch):
    from weather.operations import location_config_refresh as refresh
    calls = []
    def fetch(url, **kwargs):
        calls.append((url, kwargs))
        return [{'id': 1}] if len(calls) == 1 else []
    monkeypatch.setattr(refresh, 'json_request', fetch)
    assert refresh.fetch_gamma_events(limit=1) == ([{'id': 1}], [0, 1])
    assert all(call[1]['max_bytes'] == 16 * 1024 * 1024 for call in calls)
