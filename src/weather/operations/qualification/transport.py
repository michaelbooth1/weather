"""Authenticated, bounded GitHub reads; credentials never cross redirects.

No generic URL fetcher, shell transport, arbitrary callback or remote execution.
The source-control principal calls this outside S4U; host consumers stay offline.
"""

from __future__ import annotations

import hashlib
import http.client
import os
from pathlib import Path
import re
import ssl
import time
from urllib.parse import urlsplit

from .records import MAX_RECORD_BYTES, checked_root, decode, digest, integer, relative_path, require


class Github:
    def __init__(self, repository, token, *, deadline_seconds=120):
        require(type(repository) is str and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository), "invalid GitHub repository")
        require(type(token) is str and 0 < len(token) <= 4096 and not any(ord(c) < 33 for c in token), "authenticated GitHub token required")
        integer(deadline_seconds, minimum=1, maximum=600)
        self.repository, self._token = repository, token
        self.deadline = time.monotonic() + deadline_seconds
        self.context = ssl.create_default_context()

    def _remaining(self):
        remaining = self.deadline - time.monotonic()
        require(remaining > 0, "authenticated import deadline exceeded")
        return min(remaining, 15)

    def _endpoint(self, path):
        prefix = "/repos/" + self.repository + "/actions/"
        require(type(path) is str and path.startswith(prefix) and len(path) <= 1024 and
                re.fullmatch(r"[A-Za-z0-9_./?=&-]+", path) and ".." not in path and "//" not in path,
                "unapproved authenticated GitHub endpoint")

    def _request(self, host, path, *, authenticated):
        connection = http.client.HTTPSConnection(host, 443, timeout=self._remaining(), context=self.context)
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": "weather-qualification-importer", "Accept-Encoding": "identity"}
        if authenticated:
            require(host == "api.github.com", "authentication cannot leave GitHub API")
            headers["Authorization"] = "Bearer " + self._token
        try:
            connection.request("GET", path, headers=headers)
            response = connection.getresponse()
            require(response.getheader("Content-Encoding", "identity") == "identity", "encoded GitHub response unsupported")
            return connection, response
        except Exception:
            connection.close()
            # Do not include a signed redirect query or request headers in errors.
            raise RuntimeError("authenticated GitHub transport failed") from None

    def json(self, endpoint):
        self._endpoint(endpoint)
        connection, response = self._request("api.github.com", endpoint, authenticated=True)
        try:
            require(response.status == 200 and not response.getheader("Link"), "incomplete/non-success GitHub response")
            raw = bytearray()
            while block := response.read(min(65536, MAX_RECORD_BYTES + 1 - len(raw))):
                self._remaining()
                raw.extend(block)
                require(len(raw) <= MAX_RECORD_BYTES, "GitHub metadata exceeds bound")
            require(bool(raw), "empty GitHub metadata")
            decode(bytes(raw))
            return bytes(raw)
        finally:
            response.close()
            connection.close()

    def artifact(self, artifact_id, *, root, name, sha256, size):
        require(type(artifact_id) is str and re.fullmatch(r"[1-9][0-9]{0,19}", artifact_id), "invalid artifact ID")
        root = checked_root(root)
        name = relative_path(name)
        digest(sha256)
        integer(size, minimum=1, maximum=512 * 1024**2)
        target = root / name
        checked_root(target.parent)
        endpoint = "/repos/" + self.repository + "/actions/artifacts/" + artifact_id + "/zip"
        connection, response = self._request("api.github.com", endpoint, authenticated=True)
        try:
            require(response.status == 302, "GitHub did not supply an artifact redirect")
            location = urlsplit(response.getheader("Location", ""))
            require(location.scheme == "https" and location.port in {None, 443} and not location.username and
                    not location.password and not location.fragment and location.hostname is not None,
                    "unsafe artifact redirect")
            host = location.hostname
            require(host.endswith(".blob.core.windows.net") or host.endswith(".actions.githubusercontent.com") or
                    host == "objects.githubusercontent.com", "artifact redirect has an unapproved storage host")
        finally:
            response.close()
            connection.close()
        # A separate request deliberately has no Authorization header and never
        # follows another redirect. The authenticated expected digest is final.
        connection, response = self._request(host, location.path + ("?" + location.query if location.query else ""), authenticated=False)
        try:
            require(response.status == 200, "artifact storage response failed")
            declared = response.getheader("Content-Length")
            require(declared is not None and declared.isascii() and declared.isdigit() and int(declared) == size,
                    "artifact storage size differs")
            hasher, count = hashlib.sha256(), 0
            with target.open("xb") as output:
                while block := response.read(min(1024 * 1024, size + 1 - count)):
                    self._remaining()
                    count += len(block)
                    require(count <= size, "artifact exceeds authenticated size")
                    output.write(block)
                    hasher.update(block)
                output.flush()
                os.fsync(output.fileno())
            require(count == size and hasher.hexdigest() == sha256, "artifact differs from authenticated digest")
            return {"path": name, "sha256": sha256, "size": size}
        finally:
            response.close()
            connection.close()
