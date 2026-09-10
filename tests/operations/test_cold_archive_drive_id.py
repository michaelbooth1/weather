"""Bounded exact-ID Drive reads with synthetic credentials and network responses."""
from datetime import datetime, timedelta, timezone
import io
import json
from types import SimpleNamespace
import time

import pytest

from weather.operations import cold_archive_drive_id as drive


def client():
    document = {"r": {"type": "drive", "scope": "drive.file", "token": json.dumps({
        "access_token": "synthetic-private-token",
        "expiry": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()})}}
    return SimpleNamespace(remote="r", root_folder_id="root_123456789",
                           run=lambda *a, **kw: (0, json.dumps(document).encode()),
                           guard=lambda: True, admission=lambda: True,
                           deadline=time.monotonic() + 30)


def metadata():
    return {"id": "object_123456789", "name": "a.bin", "size": "3",
            "mimeType": "application/octet-stream", "parents": ["root_123456789"],
            "trashed": False, "sha256Checksum": "a" * 64}


def test_credential_remains_private_and_scope_is_exact():
    assert drive.token(client()) == "synthetic-private-token"
    c = client()
    c.run = lambda *a, **kw: (0, json.dumps({"r": {"type": "drive", "scope": "drive"}}).encode())
    with pytest.raises(ValueError, match="restricted Drive"):
        drive.token(c)


@pytest.mark.parametrize("field,value", [
    ("id", "different_123456"), ("name", "other.bin"), ("parents", ["other_123456789"]),
    ("trashed", True), ("mimeType", "application/vnd.google-apps.shortcut"),
    ("size", "-1"), ("sha256Checksum", "x" * 64),
])
def test_metadata_identity_and_checksum_must_match(monkeypatch, field, value):
    data = metadata()
    data[field] = value
    monkeypatch.setattr(drive, "response", lambda *a, **kw: io.BytesIO(json.dumps(data).encode()))
    with pytest.raises(ValueError):
        drive.object_metadata(client(), "a.bin", "object_123456789")


def test_metadata_returns_full_identity_without_a_name_lookup(monkeypatch):
    monkeypatch.setattr(drive, "response", lambda *a, **kw: io.BytesIO(json.dumps(metadata()).encode()))
    assert drive.object_metadata(client(), "a.bin", "object_123456789") == {
        "object_id": "object_123456789", "remote_key": "a.bin",
        "bytes": 3, "hashes": {"sha256": "a" * 64}}


def test_metadata_bound(monkeypatch):
    monkeypatch.setattr(drive, "response", lambda *a, **kw: io.BytesIO(b"x" * 65537))
    with pytest.raises(ValueError, match="exceeds bound"):
        drive.object_metadata(client(), "a.bin", "object_123456789")


class Body(io.BytesIO):
    def __init__(self, data, length="3"):
        super().__init__(data)
        self.headers = {"Content-Length": length}


@pytest.mark.parametrize("data,length,match", [
    (b"ab", "3", "truncated"), (b"abcd", "3", "exceeded"), (b"abc", "4", "length differs"),
])
def test_incomplete_or_oversized_download_never_qualifies(tmp_path, monkeypatch, data, length, match):
    monkeypatch.setattr(drive, "response", lambda *a, **kw: Body(data, length))
    with pytest.raises(ValueError, match=match):
        drive.download(client(), "object_123456789", tmp_path / "download", 3)


def test_download_is_create_only_and_retains_verified_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(drive, "response", lambda *a, **kw: Body(b"abc"))
    target = tmp_path / "download"
    drive.download(client(), "object_123456789", target, 3)
    assert target.read_bytes() == b"abc"
    with pytest.raises(ValueError, match="already exists"):
        drive.download(client(), "object_123456789", target, 3)


def test_redirects_are_never_followed():
    assert drive.NoRedirect().redirect_request(None, None, 302, "", {}, "https://invalid.example") is None


def test_id_cannot_change_the_request_host():
    with pytest.raises(ValueError, match="invalid committed"):
        drive.response(client(), "../other?token=value")


def test_response_uses_only_exact_google_id_and_clears_auth_header(monkeypatch):
    seen = []
    class Result(Body):
        status = 200
        def geturl(self):
            return seen[0].full_url
    class Opener:
        def open(self, request, timeout):
            assert request.get_header("Authorization") == "Bearer synthetic-private-token"
            seen.append(request)
            return Result(b"abc")
    monkeypatch.setattr(drive.urllib.request, "build_opener", lambda *a: Opener())
    with drive.response(client(), "object_123456789", media=True) as stream:
        assert stream.read() == b"abc"
    assert seen[0].full_url == "https://www.googleapis.com/drive/v3/files/object_123456789?alt=media"
    assert seen[0].get_header("Authorization") is None



def test_phase_lifetime_is_checked_before_payload():
    c = client()
    value = {"r": {"type": "drive", "scope": "drive.file", "token": json.dumps({
        "access_token": "synthetic", "expiry": (
            datetime.now(timezone.utc) + timedelta(seconds=600)).isoformat()})}}
    c.run = lambda *a, **kw: (0, json.dumps(value).encode())
    assert drive.token(c) == "synthetic"
    with pytest.raises(ValueError, match="separate refresh"):
        drive.token(c, minimum_remaining_seconds=930)
