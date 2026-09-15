"""HTTP state-machine tests: exact bytes, bounded reads, no credential redirect."""

import hashlib
import io

import pytest

from weather.operations.qualification import transport
from weather.operations.qualification.records import QualificationError


class Response(io.BytesIO):
    def __init__(self, body, status=200, headers=None):
        super().__init__(body)
        self.status, self.headers = status, headers or {}

    def getheader(self, name, default=None):
        return self.headers.get(name, default)


def connections(monkeypatch, responses):
    requests = []

    class Connection:
        def __init__(self, host, port, **kwargs):
            self.host = host
            assert port == 443

        def request(self, method, path, headers):
            requests.append((self.host, method, path, dict(headers)))

        def getresponse(self):
            return responses.pop(0)

        def close(self):
            pass

    monkeypatch.setattr(transport.http.client, "HTTPSConnection", Connection)
    return requests


def test_authenticated_metadata_preserves_raw_bytes(monkeypatch):
    raw = b'{ "id": 123 }\n'
    requests = connections(monkeypatch, [Response(raw)])
    client = transport.Github("owner/repo", "fixture-auth")
    assert client.json("/repos/owner/repo/actions/runs/123") == raw
    assert requests[0][0] == "api.github.com"
    assert requests[0][3]["Authorization"] == "Bearer fixture-auth"


def test_artifact_redirect_never_receives_credentials(monkeypatch, tmp_path):
    raw = b"zip fixture"
    requests = connections(monkeypatch, [Response(b"", 302, {"Location": "https://fixture.blob.core.windows.net/artifact?sig=fixture"}),
                                         Response(raw, headers={"Content-Length": str(len(raw))})])
    client = transport.Github("owner/repo", "fixture-auth")
    ref = client.artifact("123", root=tmp_path, name="artifact.zip", sha256=hashlib.sha256(raw).hexdigest(), size=len(raw))
    assert (tmp_path / ref["path"]).read_bytes() == raw
    assert "Authorization" in requests[0][3]
    assert "Authorization" not in requests[1][3]


@pytest.mark.parametrize("location", ["http://fixture.blob.core.windows.net/file", "https://evil.example/file",
                                      "https://api.github.com@evil.example/file", "https://evil.example:444/file",
                                      "https://fixture.blob.core.windows.net@evil.example/file"])
def test_unapproved_artifact_redirect_refuses_before_storage_request(monkeypatch, tmp_path, location):
    requests = connections(monkeypatch, [Response(b"", 302, {"Location": location})])
    client = transport.Github("owner/repo", "fixture-auth")
    with pytest.raises(QualificationError):
        client.artifact("123", root=tmp_path, name="artifact.zip", sha256="a" * 64, size=1)
    assert len(requests) == 1
    assert not (tmp_path / "artifact.zip").exists()


@pytest.mark.parametrize("body,headers", [(b'{"x":1,"x":2}', {}),
                                         (b'{"id":123}', {"Link": "next-page"}),
                                         (b'{"id":123}', {"Content-Encoding": "gzip"}),
                                         (b"x" * (2 * 1024**2 + 1), {})],
                         ids=["duplicate-key", "pagination", "content-encoding", "oversized-body"])
def test_incomplete_or_ambiguous_metadata_cannot_be_sealed(monkeypatch, body, headers):
    connections(monkeypatch, [Response(body, headers=headers)])
    with pytest.raises((QualificationError, RuntimeError)):
        transport.Github("owner/repo", "fixture-auth").json("/repos/owner/repo/actions/runs/123")


def test_endpoint_cannot_escape_authorized_repository():
    client = transport.Github("owner/repo", "fixture-auth")
    with pytest.raises(QualificationError):
        client.json("/repos/another/repo/actions/runs/123")
