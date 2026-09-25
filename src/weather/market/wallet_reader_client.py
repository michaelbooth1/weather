"""GET-only production-side LAN reader client; no venue credentials."""
from __future__ import annotations

import argparse
import json
import re
from urllib.parse import urlencode, urlsplit
from urllib.request import Request

from weather.market.wallet_reader_security import ReaderError, SecretGuard, lan_ip
from weather.market.wallet_reader_transport import NoRedirect
from weather.operations.live_path_security import validate_regular_nonreparse_file
from weather.paths import config_path

CLIENT_ROUTES = {"summary", "open-orders", "positions", "trades", "rewards"}


def read_account(command, *, since=None, day=None, config=None, opener=None):
    """No arbitrary path, URL, header, or method accepted from the caller."""
    try:
        if command not in CLIENT_ROUTES or since is not None and command != "trades" or day is not None and command != "rewards":
            raise ReaderError("client_route_refused")
        path = validate_regular_nonreparse_file(config if config is not None else config_path("local", "wallet_reader_client.json"))
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or set(value) != {"url", "token"}:
            raise ReaderError("client_config_invalid")
        url, token = value["url"], value["token"]
        parts = urlsplit(url)
        lan_ip(parts.hostname)
        if (parts.scheme != "http" or parts.username or parts.password or parts.query or parts.fragment
                or parts.path not in ("", "/") or parts.port is None or not 1 <= parts.port <= 65535
                or not re.fullmatch(r"[0-9a-fA-F]{64}", token)):
            raise ReaderError("client_config_invalid")
        guard = SecretGuard((token,))
        query = {}
        if since is not None:
            from weather.market.wallet_reader import valid_since
            query["since"] = valid_since(since)
        if day is not None:
            from weather.market.wallet_reader import valid_date
            query["date"] = valid_date(day)
        target = url.rstrip("/") + "/" + command + ("?" + urlencode(query) if query else "")
        request = Request(target, method="GET", headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
        if opener is None:
            from urllib.request import ProxyHandler, build_opener
            opener = build_opener(ProxyHandler({}), NoRedirect())
        with opener.open(request, timeout=5) as response:
            raw = response.read(2_000_001)
            if response.status != 200 or response.geturl() != target or len(raw) > 2_000_000:
                raise ReaderError("client_response_refused")
            return guard.clean(json.loads(raw))
    except Exception:
        raise ReaderError("wallet_reader_client_failed") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=sorted(CLIENT_ROUTES))
    parser.add_argument("--since", help="Unix seconds; trades only")
    parser.add_argument("--date", help="UTC YYYY-MM-DD; rewards only")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(read_account(args.command, since=args.since, day=args.date), allow_nan=False))
    except ReaderError:
        print(json.dumps({"error": "wallet_reader_client_failed"}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
