"""Two fixed LAN GETs; no venue credential, redirect, proxy or mutation path."""
import ipaddress
import json
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from maker_core.evidence.journal import SecretGuard


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def read_archive(url, credentials, since, *, opener=None):
    try:
        parts = urlsplit(url)
        address = ipaddress.IPv4Address(parts.hostname)
        networks = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
        if (not any(address in ipaddress.ip_network(n) for n in networks)
                or parts.port is None or not 1 <= parts.port <= 65535
                or url != f"http://{address}:{parts.port}" or credentials["url"].rstrip("/") != url
                or isinstance(since, bool) or not isinstance(since, int) or since < 0):
            raise ValueError
        opener = opener or build_opener(ProxyHandler({}), NoRedirect())
        guard = SecretGuard((credentials["token"],))
        result = {}
        for route, query in (("summary", {"include_resolved": "true"}), ("trades", {"since": since})):
            target = url + "/" + route + "?" + urlencode(query)
            request = Request(target, method="GET", headers={"Authorization": "Bearer " + credentials["token"]})
            with opener.open(request, timeout=20) as response:
                raw = response.read(2_000_001)
                if response.status != 200 or response.geturl() != target or len(raw) > 2_000_000:
                    raise ValueError
                value = json.loads(raw)
                if credentials["token"] in json.dumps(value, ensure_ascii=True):
                    raise ValueError
                # Refuse residual token text, but retain public token_id fields:
                # the general journal guard intentionally strips any token key.
                guard.clean(value)
                if not isinstance(value, dict):
                    raise ValueError
                result[route] = value
        result["account_id"] = result["summary"]["account_id"]
        result["captured_at_utc"] = result["summary"]["captured_at_utc"]
        return result
    except Exception:
        raise ValueError("portfolio_reader_unavailable") from None
