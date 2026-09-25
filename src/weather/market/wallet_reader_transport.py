"""Single GET-only upstream boundary; no redirects, proxies, SDK, or retries."""
from __future__ import annotations

import base64
from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import hmac
import json
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from weather.market.wallet_reader_security import CLOB, DATA, GAMMA, CONDITION, ReaderError
from weather.paths import data_path
from weather.schema_registry import schema_version

# Exact paths and exact query-name sets, not prefix permissions. In particular,
# /balance-allowance/update is a mutating GET and is intentionally absent.
ALLOWED = {
    (CLOB, "/data/orders"): {"next_cursor"},
    (CLOB, "/data/trades"): {"next_cursor", "maker_address", "after"},
    (CLOB, "/balance-allowance"): {"asset_type", "signature_type"},
    (CLOB, "/rewards/user"): {"date", "signature_type", "next_cursor"},
    (CLOB, "/rewards/user/total"): {"date", "signature_type"},
    (CLOB, "/rewards/user/percentages"): {"signature_type"},
    (CLOB, "/book"): {"token_id"},
    (DATA, "/positions"): {"user", "limit", "offset", "sizeThreshold"},
    (DATA, "/trades"): {"user", "limit", "offset", "takerOnly"},
    (DATA, "/activity"): {"user", "limit", "offset", "start", "sortBy", "sortDirection"},
    (GAMMA, "/markets"): {"condition_ids", "limit"},
}
AUTH_PATHS = frozenset(p for (h, p) in ALLOWED if h == CLOB and p != "/book")
MAX_BODY = 2_000_000


def check_request(method, host, path, params):
    """Refuse before building auth headers or opening any socket."""
    if method != "GET" or host not in {CLOB, DATA, GAMMA}:
        raise ReaderError("upstream_request_refused")
    keys = ALLOWED.get((host, path))
    if host == CLOB and path.startswith("/rewards/markets/") and CONDITION.fullmatch(path[17:]):
        keys = set()
    if keys is None or not isinstance(params, dict) or not set(params) <= keys:
        raise ReaderError("upstream_request_refused")
    if any(not isinstance(v, (str, int)) or isinstance(v, bool) or len(str(v)) > 256
           or any(ord(c) < 32 for c in str(v)) for v in params.values()):
        raise ReaderError("upstream_query_refused")
    if path == "/balance-allowance" and params.get("asset_type") != "COLLATERAL":
        raise ReaderError("upstream_query_refused")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # urllib raises HTTPError with the original redirect status.


def direct_opener():
    return build_opener(ProxyHandler({}), NoRedirect())


class ReadTransport:
    def __init__(self, fields, guard, *, journal_root=None, opener=None, clock=time.monotonic,
                 wall_clock=time.time):
        self.fields, self.guard = fields, guard
        self.journal_root = journal_root if journal_root is not None else data_path("wallet_reader")
        self.opener = opener if opener is not None else direct_opener()
        self.clock, self.wall_clock = clock, wall_clock
        self.cache, self.calls = {}, deque()
        self.lock = threading.RLock()

    def _record(self, path, host, status, raw, event):
        now = datetime.fromtimestamp(self.wall_clock(), timezone.utc)
        row = self.guard.clean(dict(schema_version=schema_version("wallet_reader_request"),
            captured_at_utc=now.isoformat(), event=event, method="GET", host=host,
            path=path, status=status, sha256=hashlib.sha256(raw).hexdigest() if raw is not None else None))
        self.journal_root.mkdir(parents=True, exist_ok=True)
        with (self.journal_root / f"{now.date()}.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, allow_nan=False) + "\n")
            handle.flush()

    def request(self, method, host, path, params=None):
        params = {} if params is None else dict(params)
        check_request(method, host, path, params)
        # No arbitrary account overrides, including through internal callers.
        for key in ("user", "maker_address"):
            if key in params and params[key].lower() != self.fields["FUNDER_ADDRESS"].lower():
                raise ReaderError("account_scope_refused")
        query = urlencode(sorted(params.items()))
        url = host + path + ("?" + query if query else "")
        with self.lock:
            now = self.clock()
            self.cache = {k: v for k, v in self.cache.items() if now - v[0] < 30}
            if url in self.cache:
                _, result, failed = self.cache[url]
                if failed:
                    raise ReaderError("upstream_unavailable_cached")
                return deepcopy(result)
            while self.calls and now - self.calls[0] >= 60:
                self.calls.popleft()
            if len(self.calls) >= 30:
                raise ReaderError("upstream_minute_budget")
            headers = {"Accept": "application/json", "User-Agent": "weather-wallet-reader"}
            if host == CLOB and path in AUTH_PATHS:
                stamp = str(int(self.wall_clock()))
                secret = base64.b64decode(self.fields["API_SECRET"], altchars=b"-_", validate=True)
                signature = base64.urlsafe_b64encode(hmac.new(
                    secret, (stamp + "GET" + path).encode(), hashlib.sha256).digest()).decode()
                headers.update(POLY_ADDRESS=self.fields["WALLET_ADDRESS"],
                               POLY_API_KEY=self.fields["API_KEY"],
                               POLY_PASSPHRASE=self.fields["API_PASSPHRASE"],
                               POLY_TIMESTAMP=stamp, POLY_SIGNATURE=signature)
            request = Request(url, method="GET", headers=headers)
            # Log intent first: disk failure must prevent an unjournaled read.
            self._record(path, host, None, None, "attempt")
            self.calls.append(now)
            status, raw, result, failed = None, None, None, True
            try:
                with self.opener.open(request, timeout=4) as response:
                    status = response.status
                    raw = response.read(MAX_BODY + 1)
                    if response.geturl() != url or status != 200 or len(raw) > MAX_BODY:
                        raise ReaderError("upstream_response_refused")
                    result = self.guard.clean(json.loads(raw))
                    if not isinstance(result, (dict, list)):
                        raise ReaderError("upstream_shape_refused")
                    failed = False
            except HTTPError as exc:
                status = exc.code
                try:
                    raw = exc.read(MAX_BODY + 1)
                except Exception:
                    raw = None
                finally:
                    exc.close()
            except Exception:
                pass  # Raw network/JSON exceptions may contain auth or body data.
            finally:
                self._record(path, host, status, raw, "failed" if failed else "response")
                self.cache[url] = (self.clock(), result, failed)
            if failed:
                raise ReaderError("upstream_unavailable") from None
            return deepcopy(result)
