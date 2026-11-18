"""Gamma public HTTP encoding contract shared by listing readers."""

import gzip
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class GammaRequestError(RuntimeError):
    """An actionable public Gamma request failure."""


def gamma_request_headers(user_agent):
    # Since 2026-11-12, /events[/keyset] pages above 50 require gzip.
    return {"User-Agent": user_agent, "Accept-Encoding": "gzip"}


def gamma_json(url, *, user_agent, timeout):
    request = Request(url, headers=gamma_request_headers(user_agent))
    try:
        response = urlopen(request, timeout=timeout)
    except HTTPError as exc:
        with exc:
            detail = exc.read().decode("utf-8", errors="replace")
        raise GammaRequestError(f"Gamma HTTP {exc.code}: {detail}") from exc
    with response:
        body = response.read()
        if str(response.headers.get("Content-Encoding", "")).strip().lower() == "gzip":
            body = gzip.decompress(body)
        return json.loads(body.decode("utf-8"))
