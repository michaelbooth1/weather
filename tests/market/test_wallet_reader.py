"""Offline handoff 100a acceptance tests. Every credential is synthetic."""
import ast
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import io
import json
from pathlib import Path
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

import pytest

from weather.market import wallet_reader as core
from weather.market import wallet_reader_security as security
from weather.market import wallet_reader_transport as transport
from weather.market import wallet_reader_server as server
from weather.market import wallet_reader_client as client
from weather.paths import REPO_ROOT

FUNDER = "0x" + "1" * 40
SIGNER = "0x" + "2" * 40
CONDITION = "0x" + "a" * 64
TOKEN = "ab" * 32
FIELDS = dict(API_KEY="fixture-api-key-100a", API_SECRET=base64.urlsafe_b64encode(b"fixture-hmac-secret").decode(),
              API_PASSPHRASE="fixture-passphrase-100a", WALLET_ADDRESS=SIGNER, FUNDER_ADDRESS=FUNDER,
              CLOB_HOST=security.CLOB, CHAIN_ID="137", READER_TOKEN=TOKEN)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refused(*args, **kwargs):
        raise AssertionError("network forbidden in wallet-reader tests")
    monkeypatch.setattr(socket.socket, "connect", refused)
    monkeypatch.setattr(socket.socket, "bind", refused)
    monkeypatch.setattr(socket, "create_connection", refused)


@pytest.fixture
def guard():
    return security.SecretGuard(FIELDS[k] for k in ("API_KEY", "API_SECRET", "API_PASSPHRASE", "READER_TOKEN"))


class Reply:
    def __init__(self, request, value, status=200):
        self.request, self.status = request, status
        self.raw = value if isinstance(value, bytes) else json.dumps(value).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, count):
        return self.raw[:count]

    def geturl(self):
        return self.request.full_url


class FakeOpener:
    def __init__(self, responder=lambda req: {}):
        self.calls, self.responder = [], responder

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        return Reply(request, self.responder(request))


def wire(tmp_path, guard, opener=None, clock=lambda: 0):
    return transport.ReadTransport(dict(FIELDS), guard, opener=opener or FakeOpener(),
                                   journal_root=tmp_path / "journal", clock=clock, wall_clock=lambda: 1700000000)


@pytest.mark.parametrize("method", ["POST", "DELETE", "PUT", "PATCH", "HEAD", "OPTIONS", "TRACE", "CONNECT", "get", ""])
def test_non_get_never_opens_socket(tmp_path, guard, method):
    t = wire(tmp_path, guard)
    for host, path in transport.ALLOWED:
        with pytest.raises(security.ReaderError):
            t.request(method, host, path)
    assert not t.opener.calls
    assert not t.journal_root.exists()


@pytest.mark.parametrize("path", ["/order", "/orders", "/cancel-all", "/data/order/1", "/data/orders/",
    "/heartbeats", "/v1/heartbeats", "/auth/api-key", "/auth/derive-api-key", "/auth/anything",
    "/balance-allowance/update", "/orders-scoring", "/book/../order", "/book?x=1", "/%62ook",
    "//book", "/rewards/markets/../../order", "/rewards/markets/1", "/book#fragment", "https://evil.test/book"])
def test_unapproved_path_never_opens_socket(tmp_path, guard, path):
    t = wire(tmp_path, guard)
    with pytest.raises(security.ReaderError):
        t.request("GET", security.CLOB, path)
    assert not t.opener.calls


@pytest.mark.parametrize("host", ["http://clob.polymarket.com", "https://clob.polymarket.com.evil.test",
    "https://evil.test@clob.polymarket.com", "https://clob.polymarket.com:443", "https://127.0.0.1",
    "https://clob.polymarket.com/", security.DATA, security.GAMMA])
def test_host_path_pair_is_exact(tmp_path, guard, host):
    t = wire(tmp_path, guard)
    with pytest.raises(security.ReaderError):
        t.request("GET", host, "/data/orders")
    assert not t.opener.calls


def test_allowed_routes_and_query_restriction(tmp_path, guard):
    t = wire(tmp_path, guard)
    for host, path in transport.ALLOWED:
        params = {"asset_type": "COLLATERAL"} if path == "/balance-allowance" else {}
        t.request("GET", host, path, params)
    t.request("GET", security.CLOB, "/rewards/markets/" + CONDITION)
    before = len(t.opener.calls)
    with pytest.raises(security.ReaderError):
        t.request("GET", security.CLOB, "/book", {"redirect": "https://evil.test"})
    with pytest.raises(security.ReaderError):
        t.request("GET", security.DATA, "/positions", {"user": SIGNER})
    assert len(t.opener.calls) == before


def test_hmac_headers_match_protocol_and_never_go_to_public(tmp_path, guard):
    t = wire(tmp_path, guard)
    t.request("GET", security.CLOB, "/data/trades", {"after": "12"})
    req, timeout = t.opener.calls[0]
    expected = base64.urlsafe_b64encode(hmac.new(b"fixture-hmac-secret", b"1700000000GET/data/trades", hashlib.sha256).digest()).decode()
    assert req.get_header("Poly_signature") == expected
    assert req.get_header("Poly_address") == SIGNER
    assert req.data is None and req.get_method() == "GET" and timeout == 4
    for host, path in [(security.CLOB, "/book"), (security.CLOB, "/rewards/markets/" + CONDITION),
                       (security.DATA, "/positions"), (security.GAMMA, "/markets")]:
        t.request("GET", host, path)
        assert not any(k.lower().startswith("poly_") for k in t.opener.calls[-1][0].headers)
    text = next(t.journal_root.glob("*.jsonl")).read_text()
    entries = [json.loads(line) for line in text.splitlines()]
    assert entries[0]["event"] == "attempt" and entries[1]["status"] == 200
    assert entries[1]["sha256"] == hashlib.sha256(b"{}").hexdigest()
    assert "headers" not in text and "after" not in text
    for secret in guard.secrets:
        assert secret not in text


def test_redirect_and_proxies_disabled():
    assert transport.NoRedirect().redirect_request(None, None, 302, "secret", {}, "https://evil.test") is None
    opener = transport.direct_opener()
    assert any(isinstance(h, transport.NoRedirect) for h in opener.handlers)
    assert not any(getattr(h, "proxies", {}) for h in opener.handlers)


def test_cache_budget_concurrency_and_no_mutation(tmp_path, guard):
    clock = [0]
    t = wire(tmp_path, guard, clock=lambda: clock[0])
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: t.request("GET", security.CLOB, "/book", {"token_id": "1"}), range(8)))
    assert len(t.opener.calls) == 1
    results[0]["corruption"] = True
    assert t.request("GET", security.CLOB, "/book", {"token_id": "1"}) == {}
    clock[0] = 30
    t.request("GET", security.CLOB, "/book", {"token_id": "1"})
    assert len(t.opener.calls) == 2
    for i in range(28):
        t.request("GET", security.CLOB, "/book", {"token_id": str(i + 2)})
    with pytest.raises(security.ReaderError, match="minute_budget"):
        t.request("GET", security.CLOB, "/book", {"token_id": "99"})
    clock[0] = 60
    t.request("GET", security.CLOB, "/book", {"token_id": "99"})
    assert len(t.opener.calls) == 31


@pytest.mark.parametrize("payload", [b"not json", b"x" * (transport.MAX_BODY + 1), b"null", b'{"x":NaN}'],
                         ids=["invalid-json", "oversized", "null", "nonfinite"])
def test_invalid_replies_are_cached_failures(tmp_path, guard, payload):
    t = wire(tmp_path, guard, FakeOpener(lambda r: payload))
    for _ in range(2):
        with pytest.raises(security.ReaderError, match="upstream_unavailable"):
            t.request("GET", security.CLOB, "/book")
    assert len(t.opener.calls) == 1


def test_secrets_in_responses_exceptions_and_journal_are_refused(tmp_path, guard):
    assert guard.clean({"POLY_API_KEY": "other-key", "headers": {"Authorization": TOKEN}, "ok": 1}) == {"ok": 1}
    for secret in guard.secrets:
        with pytest.raises(security.ReaderError, match="secret_output_refused"):
            guard.clean({"unexpected": "prefix" + secret})
    def failed(req):
        raise RuntimeError(FIELDS["API_KEY"])
    t = wire(tmp_path, guard, FakeOpener(failed))
    with pytest.raises(security.ReaderError) as error:
        t.request("GET", security.CLOB, "/data/orders")
    assert str(error.value) == "upstream_unavailable"
    assert not any(s in next(t.journal_root.glob("*.jsonl")).read_text() for s in guard.secrets)


def test_http_error_is_journaled_without_body(tmp_path, guard):
    def failed(req):
        raise HTTPError(req.full_url, 429, FIELDS["API_KEY"], {}, io.BytesIO(TOKEN.encode()))
    t = wire(tmp_path, guard, FakeOpener(failed))
    with pytest.raises(security.ReaderError):
        t.request("GET", security.CLOB, "/data/orders")
    log = next(t.journal_root.glob("*.jsonl")).read_text()
    assert json.loads(log.splitlines()[-1])["status"] == 429
    assert TOKEN not in log


def test_loader_only_selects_named_fields_and_drops_mapping(tmp_path, monkeypatch, capsys):
    import dotenv
    class Mapping(dict):
        def get(self, key, default=None):
            assert key != "POLYMM_PRIVATE_KEY"
            assert key in {"POLYMM_" + k for k in security.FIELDS}
            return super().get(key, default)
        def __getitem__(self, key):
            assert key != "POLYMM_PRIVATE_KEY"
            return super().__getitem__(key)
    mapping = Mapping({"POLYMM_" + k: v for k, v in FIELDS.items()})
    mapping["POLYMM_PRIVATE_KEY"] = "private-fixture-never-selected"
    env = tmp_path / ".env"
    env.write_text("fixture only")
    monkeypatch.setattr(security, "common_repository_root", lambda: tmp_path)
    def parse(path, *, interpolate):
        assert path == env and interpolate is False
        return mapping
    monkeypatch.setattr(dotenv, "dotenv_values", parse)
    fields, guard = security.load_owner_credentials()
    assert fields == FIELDS and mapping == {}
    assert len(guard.secrets) == 4
    assert capsys.readouterr() == ("", "")


def test_real_parser_on_synthetic_file_no_interpolation_or_env_export(tmp_path, monkeypatch, capsys):
    import os
    env = tmp_path / ".env"
    fixture = dict(FIELDS, API_PASSPHRASE="${IGNORED_INTERPOLATION}")
    env.write_text("\n".join("POLYMM_" + k + "=" + v for k, v in fixture.items()) +
                   "\nPOLYMM_PRIVATE_KEY=synthetic-not-a-private-key\ninvalid 'fixture\n")
    monkeypatch.setattr(security, "common_repository_root", lambda: tmp_path)
    monkeypatch.delenv("POLYMM_READER_TOKEN", raising=False)
    fields, _ = security.load_owner_credentials()
    assert fields["API_PASSPHRASE"] == "${IGNORED_INTERPOLATION}"
    assert "POLYMM_READER_TOKEN" not in os.environ
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("field,value", [("CLOB_HOST", "https://evil.test"), ("CHAIN_ID", "1"),
    ("READER_TOKEN", "weak"), ("WALLET_ADDRESS", "bad"), ("API_KEY", "injection\nheader"), ("API_SECRET", "!")])
def test_loader_refuses_bad_topology(tmp_path, monkeypatch, field, value):
    import dotenv
    (tmp_path / ".env").write_text("fixture")
    monkeypatch.setattr(security, "common_repository_root", lambda: tmp_path)
    mapping = {"POLYMM_" + k: v for k, v in dict(FIELDS, **{field: value}).items()}
    monkeypatch.setattr(dotenv, "dotenv_values", lambda *a, **kw: mapping)
    with pytest.raises(security.ReaderError):
        security.load_owner_credentials()


@pytest.fixture
def endpoint_fixtures():
    # Minimized documented response shapes; synthetic identifiers and amounts.
    return {"/balance-allowance": {"balance": "70000000", "allowances": {}},
            "/data/orders": {"data": [{"id": "resting", "maker_address": FUNDER, "owner": FIELDS["API_KEY"]}], "next_cursor": "LTE="},
            "/positions": [{"proxyWallet": FUNDER, "asset": "123", "conditionId": CONDITION,
                            "size": 75, "avgPrice": .43, "title": "Fixture band", "outcome": "Yes"}],
            "/book": {"asset_id": "123", "market": CONDITION,
                      "bids": [{"price": ".25", "size": "5"}, {"price": ".31", "size": "10"}],
                      "asks": [{"price": ".42", "size": "20"}, {"price": ".37", "size": "75"}]},
            "/markets": [{"conditionId": CONDITION, "closed": False, "active": True,
                          "rewardsMinSize": 100, "rewardsMaxSpread": 4.5}],
            "/rewards/markets/" + CONDITION: {"data": [{"rewards_daily_rate": "73"}], "next_cursor": "LTE="},
            "/data/trades": {"data": [{"price": ".43", "size": "75"}], "next_cursor": "LTE="},
            "/trades": [{"price": .43}], "/activity": [{"type": "TRADE"}],
            "/rewards/user": {"data": [{"earnings": "2.13"}], "next_cursor": "LTE="},
            "/rewards/user/total": [{"earnings": "2.13"}], "/rewards/user/percentages": {CONDITION: 0.38}}


def test_endpoint_parsing_and_summary(tmp_path, guard, endpoint_fixtures):
    t = wire(tmp_path, guard, FakeOpener(lambda r: endpoint_fixtures[urlsplit(r.full_url).path]))
    r = core.WalletReader(t, signature_type=3, campaign_capital="120")
    summary = r.summary()
    assert summary["cash_pusd"] == "70"
    assert summary["positions"][0]["mid"] == "0.34"
    assert summary["positions"][0]["reward_min_size"] == 100
    assert summary["unrealized_pnl_pusd"] == "-6.75"
    assert summary["campaign_pnl_pusd"] == "-24.50"
    assert summary["status"] == "OBSERVED"
    assert "owner" not in summary["open_orders"][0]
    assert r.trades("123")["recent_activity"] == [{"type": "TRADE"}]
    assert r.rewards("2026-09-25")["payment_verified"] is False
    assert all(req.get_method() == "GET" for req, _ in t.opener.calls)
    assert len(t.opener.calls) <= 30


@pytest.mark.parametrize("cash,capital,status,pnl", [("60", "100", "OBSERVED", "-40"),
    ("59.99", "60", "BLEED_LIMIT", "-0.01"), ("60", "100.01", "BLEED_LIMIT", "-40.01"),
    ("60", None, "INCOMPLETE", None), ("59", None, "BLEED_LIMIT", None)])
def test_bleed_boundaries(cash, capital, status, pnl):
    value = core.portfolio_summary({"cash_pusd": cash}, [], [], capital)
    assert value["status"] == status and value["campaign_pnl_pusd"] == pnl


def test_incomplete_mark_does_not_invent_pnl(tmp_path, guard, endpoint_fixtures):
    endpoint_fixtures["/book"]["asks"] = []
    t = wire(tmp_path, guard, FakeOpener(lambda r: endpoint_fixtures[urlsplit(r.full_url).path]))
    value = core.WalletReader(t, signature_type=2, campaign_capital=120).summary()
    assert value["campaign_pnl_pusd"] is None and value["status"] == "INCOMPLETE"
    assert value["positions"][0]["mark_value_pusd"] is None


def test_pages_follow_cursor_and_refuse_repeat(tmp_path, guard):
    def respond(req):
        if parse_qs(urlsplit(req.full_url).query).get("next_cursor"):
            return {"data": [{"id": 2}], "next_cursor": "LTE="}
        return {"data": [{"id": 1}], "next_cursor": "Mg=="}
    t = wire(tmp_path, guard, FakeOpener(respond))
    r = core.WalletReader(t, signature_type=2)
    assert r.pages("/data/orders") == [{"id": 1}, {"id": 2}]
    t = wire(tmp_path, guard, FakeOpener(lambda req: {"data": [], "next_cursor": "Mg=="}))
    with pytest.raises(security.ReaderError, match="cursor"):
        core.WalletReader(t, signature_type=2).pages("/data/orders")


@pytest.mark.parametrize("ip", ["0.0.0.0", "127.0.0.1", "8.8.8.8", "169.254.1.1", "100.64.0.1", "::1", "192.0.2.1", "172.32.0.1"])
def test_server_rejects_non_rfc1918_before_bind(ip, guard):
    with pytest.raises(security.ReaderError):
        server.serve_reader(None, guard, TOKEN, bind=ip, allow="192.168.1.5", port=8765)


@pytest.mark.parametrize("ip", ["10.0.0.1", "172.16.0.1", "172.31.255.254", "192.168.1.2"])
def test_rfc1918_valid(ip):
    assert security.lan_ip(ip) == ip


class NoReader:
    def __getattr__(self, name):
        raise AssertionError("rejected request reached upstream")


@pytest.mark.parametrize("method,target,ip,headers,status", [
    ("GET", "/summary", "192.168.1.5", {}, 401),
    ("GET", "/summary", "192.168.1.5", {"Authorization": "Bearer wrong"}, 401),
    ("GET", "/summary", "192.168.1.6", {"Authorization": "Bearer " + TOKEN}, 403),
    ("DELETE", "/summary", "192.168.1.5", {"Authorization": "Bearer " + TOKEN}, 405),
    ("POST", "/summary", "192.168.1.5", {"Authorization": "Bearer " + TOKEN}, 405),
    ("GET", "/auth/api-key", "192.168.1.5", {"Authorization": "Bearer " + TOKEN}, 404),
    ("GET", "http://evil.test/summary", "192.168.1.5", {"Authorization": "Bearer " + TOKEN}, 404),
    ("GET", "/summary?x=1", "192.168.1.5", {"Authorization": "Bearer " + TOKEN}, 400),
    ("GET", "/summary", "192.168.1.5", {"Authorization": "Bearer " + TOKEN, "Origin": "https://evil.test"}, 403),
])
def test_server_rejected_requests_never_touch_upstream(guard, method, target, ip, headers, status):
    code, value = server.dispatch(NoReader(), guard, TOKEN, "192.168.1.5", method, target, ip, headers)
    assert code == status


def test_health_and_exception_scrubbing(guard):
    args = (guard, TOKEN, "192.168.1.5", "GET", "/health", "192.168.1.5", {"Authorization": "Bearer " + TOKEN})
    code, value = server.dispatch(NoReader(), *args)
    assert code == 200 and value == {"status": "ok", "upstream_checked": False}
    class Exploding:
        def summary(self, **kwargs):
            raise RuntimeError(TOKEN)
    code, value = server.dispatch(Exploding(), guard, TOKEN, "192.168.1.5", "GET", "/summary", "192.168.1.5", args[-1])
    assert code == 503 and TOKEN not in json.dumps(value)


def test_http_handler_in_memory_no_socket(guard):
    class Connection:
        def __init__(self):
            self.input = io.BytesIO(("GET /health HTTP/1.0\r\nAuthorization: Bearer " + TOKEN + "\r\n\r\n").encode())
            self.output = bytearray()
        def makefile(self, *args):
            return self.input
        def sendall(self, data):
            self.output.extend(data)
    connection = Connection()
    server.handler_for(NoReader(), guard, TOKEN, "192.168.1.5")(connection, ("192.168.1.5", 1000), None)
    reply = connection.output.decode()
    assert "200 OK" in reply and '"status": "ok"' in reply
    assert "Access-Control" not in reply and TOKEN not in reply


def test_client_twenty_second_get_and_secret_refusal(tmp_path):
    config = tmp_path / "client.json"
    config.write_text(json.dumps({"url": "http://192.168.1.2:8765", "token": TOKEN}))
    opener = FakeOpener(lambda r: {"status": "OBSERVED"})
    assert client.read_account("summary", config=config, opener=opener) == {"status": "OBSERVED"}
    req, timeout = opener.calls[0]
    assert req.get_method() == "GET" and timeout == 20 and req.data is None
    assert req.get_header("Authorization") == "Bearer " + TOKEN
    with pytest.raises(security.ReaderError):
        client.read_account("summary", config=config, opener=FakeOpener(lambda r: {"unexpected": TOKEN}))
    config.write_text(json.dumps({"url": "http://8.8.8.8:8765", "token": TOKEN}))
    with pytest.raises(security.ReaderError):
        client.read_account("summary", config=config, opener=opener)
    assert len(opener.calls) == 1


def test_no_signing_imports_and_no_unapproved_file_access():
    permitted = {"__future__", "argparse", "base64", "collections", "contextlib", "copy", "datetime",
                 "decimal", "dotenv", "hashlib", "hmac", "http", "io", "ipaddress", "json", "logging", "math",
                 "pathlib", "re", "subprocess", "threading", "time", "urllib", "weather"}
    weather_allowed = {"weather.market.wallet_reader", "weather.market.wallet_reader_security",
                       "weather.market.wallet_reader_transport", "weather.market.wallet_reader_server",
                       "weather.operations.live_path_security", "weather.paths", "weather.schema_registry"}
    for name in ("wallet_reader", "wallet_reader_security", "wallet_reader_transport", "wallet_reader_server", "wallet_reader_client"):
        source = (REPO_ROOT / "src/weather/market" / (name + ".py")).read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imports = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module]
                for module in imports:
                    assert module.split(".")[0] in permitted
                    if module.startswith("weather."):
                        assert module in weather_allowed
        assert "POLYMM_PRIVATE_KEY" not in source
        assert "os.environ" not in source
        assert "dotenv_values" not in source or name == "wallet_reader_security"
        assert "Account.from_key" not in source and "py_clob_client" not in source


def test_firewall_scope_and_whatif_structure():
    script = (REPO_ROOT / "scripts/ops/register_wallet_reader_firewall.ps1").read_text()
    assert "SupportsShouldProcess = $true" in script
    assert "-RemoteAddress $AllowIp -Profile Private" in script
    assert "[switch]$Unregister" in script
    assert "-Name $ruleName" in script


def test_invalid_startup_does_not_load_credentials(monkeypatch):
    def forbidden():
        raise AssertionError("credential loader called for invalid bind")
    monkeypatch.setattr(core, "load_owner_credentials", forbidden)
    assert core.main(["serve", "--bind", "0.0.0.0", "--allow", "192.168.1.5", "--signature-type", "3"]) == 1


def test_missing_credential_file_is_generic_and_parser_errors_silent(tmp_path, monkeypatch, capsys):
    import dotenv
    monkeypatch.setattr(security, "common_repository_root", lambda: tmp_path)
    with pytest.raises(security.ReaderError, match="credential_file_unreadable"):
        security.load_owner_credentials()
    (tmp_path / ".env").write_text("fixture")
    def explode(*args, **kwargs):
        raise ValueError(TOKEN)
    monkeypatch.setattr(dotenv, "dotenv_values", explode)
    with pytest.raises(security.ReaderError, match="credential_file_unreadable"):
        security.load_owner_credentials()
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("field,replacement", [("proxyWallet", SIGNER), ("conditionId", "bad"), ("asset", "../order")])
def test_position_identity_fails_closed(tmp_path, guard, endpoint_fixtures, field, replacement):
    endpoint_fixtures["/positions"][0][field] = replacement
    t = wire(tmp_path, guard, FakeOpener(lambda r: endpoint_fixtures[urlsplit(r.full_url).path]))
    value = core.WalletReader(t, signature_type=3).positions()
    assert value["errors"] == {"positions": "positions_unavailable"}
    assert value["positions"] == [] and value["status"] == "PARTIAL"


def test_other_funder_open_order_is_not_silently_dropped(tmp_path, guard):
    t = wire(tmp_path, guard, FakeOpener(lambda r: {"data": [{"maker_address": SIGNER}], "next_cursor": "LTE="}))
    with pytest.raises(security.ReaderError, match="account_mismatch"):
        core.WalletReader(t, signature_type=3).open_orders()


def test_client_cli_exception_does_not_print_secrets(monkeypatch, capsys):
    def failed(*args, **kwargs):
        raise security.ReaderError(TOKEN)
    monkeypatch.setattr(client, "read_account", failed)
    assert client.main(["summary"]) == 1
    assert TOKEN not in capsys.readouterr().out


def inventory_fixture(live=4, resolved=100):
    """Resolved dust deliberately precedes valuable live lots in API order."""
    holdings = [dict(proxyWallet=FUNDER, asset=str(i + 1), conditionId="0x" + f"{i + 1:064x}",
                     size=i + 1 if i >= resolved else .01, avgPrice=.4,
                     curPrice=.5 if i >= resolved else 0, redeemable=i < resolved,
                     endDate="2026-01-01") for i in range(live + resolved)]
    markets = [dict(conditionId=p["conditionId"], closed=i < resolved, active=i >= resolved,
                    rewardsMinSize=10, rewardsMaxSpread=4) for i, p in enumerate(holdings)]

    def respond(req):
        parts = urlsplit(req.full_url)
        query = parse_qs(parts.query)
        if parts.path == "/positions":
            offset = int(query["offset"][0])
            return holdings[offset:offset + 100]
        if parts.path == "/markets":
            assert set(query["condition_ids"]) == {p["conditionId"] for p in holdings}
            return markets
        if parts.path == "/balance-allowance":
            return {"balance": "70000000"}
        if parts.path == "/data/orders":
            return {"data": [], "next_cursor": "LTE="}
        if parts.path == "/book":
            p = next(p for p in holdings if p["asset"] == query["token_id"][0])
            assert not p["redeemable"], "resolved position requested a book"
            return dict(asset_id=p["asset"], market=p["conditionId"],
                        bids=[{"price": ".4", "size": "100"}], asks=[{"price": ".6", "size": "100"}])
        if parts.path.startswith("/rewards/markets/"):
            assert parts.path.split("/")[-1] in {p["conditionId"] for p in holdings if not p["redeemable"]}
            return {"data": [{"rewards_daily_rate": "10"}], "next_cursor": "LTE="}
        raise AssertionError("unexpected fixture endpoint")
    return holdings, markets, respond


def test_104_positions_only_four_live_books_and_one_metadata_batch(tmp_path, guard):
    holdings, _, respond = inventory_fixture()
    t = wire(tmp_path, guard, FakeOpener(respond))
    reader = core.WalletReader(t, signature_type=2, campaign_capital=200)
    result = reader.summary(include_resolved=True)
    assert len(result["positions"]) == 4 and len(result["resolved_positions"]) == 100
    assert all(p["mid"] == "0.5" and not p["errors"] for p in result["positions"])
    assert all(p["redeemable"] and p["last_price"] == "0" for p in result["resolved_positions"])
    assert result["plan"]["used_gets"] == len(t.opener.calls) == 13
    assert result["plan"]["deferred_live_positions"] == 0
    paths = [urlsplit(req.full_url).path for req, _ in t.opener.calls]
    assert paths.count("/book") == 4 and paths.count("/markets") == 1
    assert paths.count("/positions") == 2
    assert all(req.get_method() == "GET" for req, _ in t.opener.calls)
    hidden = reader.summary()
    assert "resolved_positions" not in hidden and hidden["resolved_count"] == 100
    assert hidden["campaign_pnl_pusd"] == result["campaign_pnl_pusd"]
    assert len(t.opener.calls) == 13  # Per-read cache, no new upstream calls.


def test_overflow_prioritizes_value_and_returns_partial_inventory(tmp_path, guard):
    _, _, respond = inventory_fixture(live=20, resolved=0)
    t = wire(tmp_path, guard, FakeOpener(respond))
    result = core.WalletReader(t, signature_type=2, campaign_capital=200).summary()
    assert result["plan"]["used_gets"] == 24
    assert [p["token_id"] for p in result["positions"][:10]] == [str(i) for i in range(20, 10, -1)]
    assert all(p["mid"] == "0.5" for p in result["positions"][:10])
    assert all(p["errors"] == ["budget_deferred"] for p in result["positions"][10:])
    assert result["plan"]["deferred_live_positions"] == 10
    assert result["cash_pusd"] == "70" and result["open_orders"] == []
    assert result["campaign_pnl_pusd"] is None and result["status"] == "INCOMPLETE"


def test_remaining_minute_budget_and_cached_reads_cost_zero(tmp_path, guard):
    _, _, respond = inventory_fixture(live=4, resolved=0)
    t = wire(tmp_path, guard, FakeOpener(respond))
    # Prior attempts consume 24 of the minute allowance; two discovery calls
    # leave room for the two highest-value positions only.
    t.calls.extend([0] * 24)
    reader = core.WalletReader(t, signature_type=2)
    result = reader.positions()
    assert result["plan"]["max_gets"] == result["plan"]["used_gets"] == 6
    assert [p["token_id"] for p in result["positions"] if p["mid"]] == ["4", "3"]
    cached = reader.positions()
    assert cached["plan"]["used_gets"] == 0
    assert [p["token_id"] for p in cached["positions"] if p["mid"]] == ["4", "3"]
    assert len(t.opener.calls) == 6


def test_failed_book_does_not_poison_cash_or_orders_and_expires_at_ten(tmp_path, guard):
    _, _, respond = inventory_fixture(live=1, resolved=0)
    clock = [0]
    fail = [True]
    def endpoint(req):
        if urlsplit(req.full_url).path == "/book" and fail[0]:
            raise HTTPError(req.full_url, 404, TOKEN, {}, io.BytesIO(b"fixture missing book"))
        return respond(req)
    t = wire(tmp_path, guard, FakeOpener(endpoint), clock=lambda: clock[0])
    reader = core.WalletReader(t, signature_type=2, campaign_capital=100)
    first = reader.summary()
    assert first["positions"][0]["errors"] == ["book_mark_unavailable"]
    count = len(t.opener.calls)
    assert reader.open_orders() == [] and reader.balance()["cash_pusd"] == "70"
    fail[0] = False
    clock[0] = 9.999
    assert reader.summary()["positions"][0]["mid"] is None
    assert len(t.opener.calls) == count
    clock[0] = 10
    assert reader.summary()["positions"][0]["mid"] == "0.5"
    assert len(t.opener.calls) == count + 1  # Only the failed book expires.


@pytest.mark.parametrize("failed_path,field,error", [
    ("/balance-allowance", "cash_pusd", "cash"), ("/data/orders", "open_orders", "open_orders"),
    ("/positions", "positions", "positions")])
def test_summary_field_failures_preserve_other_results(tmp_path, guard, failed_path, field, error):
    _, _, respond = inventory_fixture(live=1, resolved=0)
    def endpoint(req):
        if urlsplit(req.full_url).path == failed_path:
            raise TimeoutError(TOKEN)
        return respond(req)
    t = wire(tmp_path, guard, FakeOpener(endpoint))
    reader = core.WalletReader(t, signature_type=2, campaign_capital=100)
    code, result = server.dispatch(reader, guard, TOKEN, "192.168.1.5", "GET", "/summary",
                                   "192.168.1.5", {"Authorization": "Bearer " + TOKEN})
    assert code == 200 and error in result["errors"]
    assert result[field] in (None, []) and result["status"] == "INCOMPLETE"
    if field != "cash_pusd":
        assert result["cash_pusd"] == "70"
    if field != "positions":
        assert result["positions"][0]["mid"] == "0.5"
    assert TOKEN not in json.dumps(result)


@pytest.mark.parametrize("resolved", [0, 100])
def test_cold_composite_stops_at_time_plan_independent_of_dust(tmp_path, guard, resolved):
    _, _, respond = inventory_fixture(live=4, resolved=resolved)
    clock = [0]
    class SlowFixture(FakeOpener):
        def open(self, request, timeout):
            assert 0 < timeout <= 4 and clock[0] < transport.COMPOSITE_SECONDS
            clock[0] += min(3, timeout)
            return super().open(request, timeout)
    t = wire(tmp_path, guard, SlowFixture(respond), clock=lambda: clock[0])
    result = core.WalletReader(t, signature_type=2, campaign_capital=200).summary()
    assert clock[0] == transport.COMPOSITE_SECONDS == 16
    assert len(t.opener.calls) == 6
    assert result["cash_pusd"] == "70" and result["open_orders"] == []
    assert result["plan"]["deferred_live_positions"] > 0
    assert result["status"] == "INCOMPLETE"


def test_resolution_is_not_inferred_from_expired_date_or_zero_price(tmp_path, guard):
    holdings, markets, respond = inventory_fixture(live=1, resolved=0)
    holdings[0]["curPrice"] = 0
    markets[0].pop("closed")
    t = wire(tmp_path, guard, FakeOpener(respond))
    result = core.WalletReader(t, signature_type=2, campaign_capital=100).summary()
    assert result["positions"] == [] and result["resolved_count"] == 0
    assert result["unclassified_positions"][0]["classification"] == "unknown"
    assert result["campaign_pnl_pusd"] is None
    assert not any(urlsplit(req.full_url).path == "/book" for req, _ in t.opener.calls)


def test_resolved_winner_value_is_retained_when_hidden(tmp_path, guard):
    holdings, _, respond = inventory_fixture(live=0, resolved=1)
    holdings[0].update(curPrice=1, size=5)
    t = wire(tmp_path, guard, FakeOpener(respond))
    reader = core.WalletReader(t, signature_type=2, campaign_capital=100)
    result = reader.summary()
    assert result["marked_positions_pusd"] == "5" and result["campaign_pnl_pusd"] == "-25"
    assert "resolved_positions" not in result
    assert reader.positions(include_resolved=True)["resolved_positions"][0]["size"] == "5"


def test_gamma_closed_and_nonterminal_value_remain_explicit(tmp_path, guard):
    holdings, _, respond = inventory_fixture(live=0, resolved=1)
    holdings[0].update(redeemable=False, curPrice=.3)
    t = wire(tmp_path, guard, FakeOpener(respond))
    reader = core.WalletReader(t, signature_type=2)
    code, result = server.dispatch(reader, guard, TOKEN, "192.168.1.5", "GET",
        "/positions?include_resolved=true", "192.168.1.5", {"Authorization": "Bearer " + TOKEN})
    assert code == 200 and result["status"] == "PARTIAL" and result["positions"] == []
    assert result["resolved_positions"][0]["classification_basis"] == "gamma_closed"
    assert result["resolved_positions"][0]["errors"] == ["resolved_value_unavailable"]
    assert len(t.opener.calls) == 2


def test_missing_metadata_preserves_rows_without_speculative_books(tmp_path, guard):
    _, _, respond = inventory_fixture(live=4, resolved=100)
    def endpoint(req):
        return [] if urlsplit(req.full_url).path == "/markets" else respond(req)
    t = wire(tmp_path, guard, FakeOpener(endpoint))
    result = core.WalletReader(t, signature_type=2, campaign_capital=200).summary()
    assert len(result["unclassified_positions"]) == 4 and result["resolved_count"] == 100
    assert result["status"] == "INCOMPLETE" and result["campaign_pnl_pusd"] is None
    assert len(t.opener.calls) == 5


@pytest.mark.parametrize("params", [{"condition_ids": ["bad"]}, {"condition_ids": []},
                                      {"id": [CONDITION]}, {"condition_ids": [CONDITION] * 501}])
def test_batch_query_validation_refuses_before_socket(tmp_path, guard, params):
    t = wire(tmp_path, guard)
    with pytest.raises(security.ReaderError):
        t.request("GET", security.GAMMA, "/markets", params)
    assert not t.opener.calls


@pytest.mark.parametrize("target", ["/summary?include_resolved=1", "/positions?include_resolved=",
    "/summary?include_resolved=true&include_resolved=false", "/open-orders?include_resolved=true"])
def test_server_rejects_invalid_resolved_flag(guard, target):
    code, _ = server.dispatch(NoReader(), guard, TOKEN, "192.168.1.5", "GET", target,
                              "192.168.1.5", {"Authorization": "Bearer " + TOKEN})
    assert code == 400


@pytest.mark.parametrize("reason", ["timeout", "http_503", "http_401", "refused", "config"])
def test_client_safe_reason_codes(tmp_path, monkeypatch, capsys, reason):
    config = tmp_path / "client.json"
    config.write_text(json.dumps({"url": "http://192.168.1.20:8765", "token": TOKEN}))
    def fail(req):
        if reason == "timeout":
            raise URLError(TimeoutError(TOKEN))
        if reason.startswith("http_"):
            raise HTTPError(req.full_url, int(reason[5:]), TOKEN, {}, io.BytesIO(TOKEN.encode()))
        raise ConnectionRefusedError(TOKEN)
    if reason == "config":
        config.write_text("invalid fixture")
    with pytest.raises(client.ClientError) as caught:
        client.read_account("summary", config=config, opener=FakeOpener(fail))
    assert caught.value.reason == reason and str(caught.value) == "wallet_reader_client_failed"
    def cli_fail(*args, **kwargs):
        raise caught.value
    monkeypatch.setattr(client, "read_account", cli_fail)
    assert client.main(["summary"]) == 1
    assert json.loads(capsys.readouterr().out) == {"error": "wallet_reader_client_failed", "reason": reason}


def test_client_resolved_flag_and_five_second_timeout_floor(tmp_path):
    config = tmp_path / "client.json"
    config.write_text(json.dumps({"url": "http://192.168.1.20:8765", "token": TOKEN}))
    opener = FakeOpener()
    client.read_account("positions", config=config, opener=opener, include_resolved=True, timeout=5)
    req, timeout = opener.calls[0]
    assert timeout == 5 and parse_qs(urlsplit(req.full_url).query) == {"include_resolved": ["true"]}
    for invalid in [4.99, float("nan"), float("inf"), True, 121]:
        with pytest.raises(client.ClientError) as caught:
            client.read_account("positions", config=config, opener=opener, timeout=invalid)
        assert caught.value.reason == "refused"
    assert len(opener.calls) == 1
