"""Guards: T115 Gamma gzip-required listing transport and offline refresh."""

import gzip
import io
import json
from email.message import Message
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest

from weather.market import gamma_http
from weather.operations.location_config_refresh import fetch_gamma_events, main


@pytest.mark.parametrize("compressed", [True, False])
def test_listing_body_and_pagination(monkeypatch, compressed):
    requests = []
    pages = iter([[{"id": str(i)} for i in range(100)], [{"id": "last"}]])

    def open_page(request, *, timeout):
        requests.append(request)
        assert timeout == 7
        assert request.get_header("Accept-encoding") == "gzip"
        body = json.dumps(next(pages)).encode()
        response = io.BytesIO(gzip.compress(body) if compressed else body)
        response.headers = {"Content-Encoding": "gzip"} if compressed else {}
        return response

    monkeypatch.setattr(gamma_http, "urlopen", open_page)
    rows, offsets = fetch_gamma_events(timeout_seconds=7)
    assert offsets == [0, 100]
    assert len(rows) == 101 and rows[-1] == {"id": "last"}
    assert [parse_qs(urlsplit(r.full_url).query)["offset"] for r in requests] == [["0"], ["100"]]
    assert all(parse_qs(urlsplit(r.full_url).query)["limit"] == ["100"] for r in requests)


def test_406_includes_venue_hint_without_cli_traceback(tmp_path, monkeypatch, capsys):
    hint = "send the header Accept-Encoding: gzip"

    def refused(request, **kwargs):
        raise HTTPError(request.full_url, 406, "Not Acceptable", Message(),
                        io.BytesIO(json.dumps({"error": "gzip_required", "hint": hint}).encode()))

    monkeypatch.setattr(gamma_http, "urlopen", refused)
    locations = tmp_path / "locations.json"
    locations.write_text('{"locations": []}')
    output = tmp_path / "events.json"
    with pytest.raises(SystemExit) as exc:
        main(["--locations", str(locations), "--event-metadata", str(output)])
    assert exc.value.code == 1
    message = capsys.readouterr().err
    assert "Gamma HTTP 406" in message and "gzip_required" in message and hint in message
    assert "Traceback" not in message
    assert not output.exists()


@pytest.mark.parametrize("wrapped", [False, True])
def test_fixture_path_never_fetches(tmp_path, monkeypatch, wrapped):
    def no_network(*args, **kwargs):
        pytest.fail("fixture refresh attempted network")

    monkeypatch.setattr(gamma_http, "urlopen", no_network)
    locations = tmp_path / "locations.json"
    locations.write_text('{"locations": []}')
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps({"events": []} if wrapped else []))
    output = tmp_path / "events.json"
    main(["--locations", str(locations), "--event-metadata", str(output),
          "--events-json", str(fixture), "--metadata-only"])
    assert json.loads(output.read_text())["source"]["api_offsets_fetched"] == []
