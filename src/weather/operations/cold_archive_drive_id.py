"""Read already-committed Drive objects by immutable ID under archive admission.

Only the authenticated Google Drive API host is allowed. Configuration remains
pinned by the caller, credentials stay in memory, and every payload is create-only.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

from weather.operations import production_cold_archive_stage as archive

ID = re.compile(r"[A-Za-z0-9_-]{10,160}")
KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,190}")
MAX_METADATA = 65536
FIELDS = "id,name,size,mimeType,parents,trashed,md5Checksum,sha1Checksum,sha256Checksum"


def require(value, message):
    if not value:
        raise ValueError(message)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None  # Never forward a service credential to a redirect target.


def token(client):
    code, raw = client.run(["config", "dump"], capture=True)
    require(code == 0 and len(raw) <= MAX_METADATA, "private Drive credential read failed")
    config = json.loads(raw)
    require(isinstance(config, dict) and client.remote in config, "Drive remote missing")
    remote = config[client.remote]
    require(remote.get("type") == "drive" and remote.get("scope") == "drive.file",
            "restricted Drive credential required")
    value = json.loads(remote["token"])
    expiry = datetime.fromisoformat(value["expiry"].replace("Z", "+00:00"))
    require(expiry.tzinfo is not None
            and expiry > datetime.now(timezone.utc) + timedelta(seconds=30),
            "Drive credential needs separate refresh")
    access = value.get("access_token")
    require(isinstance(access, str) and 1 <= len(access) <= 8192
            and "\r" not in access and "\n" not in access,
            "invalid Drive access credential")
    return access


def response(client, object_id, *, media=False):
    require(isinstance(object_id, str) and ID.fullmatch(object_id), "invalid committed Drive ID")
    client.guard()
    query = "alt=media" if media else "fields=" + FIELDS
    url = "https://www.googleapis.com/drive/v3/files/" + object_id + "?" + query
    access = token(client)
    request = urllib.request.Request(
        url, headers={"Authorization": "Bearer " + access, "Accept-Encoding": "identity"},
        method="GET")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    result = None
    try:
        result = opener.open(request, timeout=min(10, max(.1, client.deadline - time.monotonic())))
        require(result.status == 200 and result.geturl() == url, "unexpected Drive response")
        client.guard()
        return result
    except Exception:
        if result is not None:
            result.close()
        raise ValueError("exact-ID Drive read failed") from None
    finally:
        request.remove_header("Authorization")
        access = ""


def object_metadata(client, key, object_id):
    require(isinstance(key, str) and KEY.fullmatch(key), "invalid committed Drive key")
    with response(client, object_id) as stream:
        raw = stream.read(MAX_METADATA + 1)
    require(len(raw) <= MAX_METADATA, "Drive metadata exceeds bound")
    client.guard()
    value = json.loads(raw)
    mime_types = ("application/octet-stream", "application/json", "text/plain") if key.endswith(".json") else ("application/octet-stream",)
    require(isinstance(value, dict) and value.get("id") == object_id
            and value.get("name") == key and value.get("trashed") is False
            and value.get("mimeType") in mime_types
            and value.get("parents") == [client.root_folder_id],
            "committed Drive identity or parent changed")
    size = value.get("size")
    require(isinstance(size, str) and re.fullmatch(r"0|[1-9][0-9]{0,12}", size),
            "invalid Drive object size")
    hashes = {}
    for field, name, length in (("md5Checksum", "md5", 32), ("sha1Checksum", "sha1", 40),
                                ("sha256Checksum", "sha256", 64)):
        if field in value:
            digest = value[field]
            require(isinstance(digest, str) and re.fullmatch("[0-9a-f]{" + str(length) + "}", digest),
                    "invalid Drive object checksum")
            hashes[name] = digest
    return {"object_id": object_id, "remote_key": key, "bytes": int(size), "hashes": hashes}


def download(client, object_id, destination, expected_bytes):
    require(type(expected_bytes) is int and 0 <= expected_bytes <=
            archive.MAX_CHUNK_BYTES + archive.MAX_CHUNK_BYTES // 100 + 4 * archive.MIB,
            "Drive download exceeds bound")
    destination = Path(destination)
    require(not destination.exists(), "download destination already exists")
    guard = archive._Guard(client.admission, client.deadline, 8 * archive.MIB)
    with response(client, object_id, media=True) as source:
        require(source.headers.get("Content-Length") == str(expected_bytes),
                "Drive download length differs from committed object")
        with destination.open("xb", buffering=0) as target:
            count = 0
            while True:
                client.guard()
                block = source.read(min(archive.MIB, expected_bytes - count + 1))
                if not block:
                    break
                require(count + len(block) <= expected_bytes, "Drive download exceeded committed size")
                require(target.write(block) == len(block), "short Drive download write")
                count += len(block)
                guard.account(len(block))
                client.guard()
            require(count == expected_bytes, "Drive download was truncated")
            target.flush()
            os.fsync(target.fileno())
    client.guard()
