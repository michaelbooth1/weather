"""Deterministic in-memory venue and non-authorizing numeric-profile fixtures."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from urllib.parse import urlencode

from weather.market.mm_geographic_eligibility import (
    PHYSICAL_LOCATION_CONFIRMATION, check_geographic_eligibility,
)
from weather.market.mm_live_envelope import STAGE2_HOLD_V1, GRANT_PREFIX, GRANT_KEY
from weather.market.mm_official_adapter import OfficialPolymarketGlobalAdapter


MAKER = "0x" + "a" * 40
CONDITION = "0x" + "b" * 64
TOKENS = ("111", "222")


class Clock:
    def __init__(self):
        self.seconds = 0.0

    def now(self):
        return datetime(2026, 9, 21, 12, tzinfo=timezone.utc) + timedelta(seconds=self.seconds)

    def monotonic(self):
        return self.seconds

    def sleep(self, seconds):
        self.seconds += seconds


def numeric_authority_fixture(root, clock):
    # Deliberately lacks the host-assignment schema and identities. It can test
    # the numeric gate but cannot seal or launch an actual stage.
    grant = {"profile_id": STAGE2_HOLD_V1.profile_id, "profile_sha256": STAGE2_HOLD_V1.sha256,
             "authorized_on": "2026-09-21", "expires_at_utc": "2026-09-21T23:59:00Z"}
    (root / "docs/operations").mkdir(parents=True)
    (root / "config").mkdir()
    (root / "docs/operations/STATE_OF_PLAY.md").write_text(
        "## Current authority\n" + GRANT_PREFIX + json.dumps(grant) + "\n", encoding="utf-8")
    (root / "config/international_live_execution_host.json").write_text(
        json.dumps({GRANT_KEY: grant}), encoding="utf-8")
    return root


class Page:
    def __init__(self, rows):
        self.rows = deepcopy(rows)

    def iter_items(self):
        return iter(self.rows)


class Venue:
    signer = MAKER

    def __init__(self, clock):
        self.clock = clock
        self.orders = {}
        self.calls = []
        self.reject_second = False
        self.fail_heartbeat_at = None
        self.fill_at = None
        self.cancel_unavailable = False
        self.last_heartbeat = None
        self.fail_geoblock_at = None
        self.public_change = None
        self.cash = "50000000"

    def advance(self):
        if self.fill_at is not None and self.clock.seconds >= self.fill_at and self.orders:
            row = next(iter(self.orders.values()))
            row.update(size_matched="1", status="MATCHED", associate_trades=["fixture-fill"])
        if self.cancel_unavailable and self.last_heartbeat is not None and self.clock.seconds - self.last_heartbeat >= 12:
            for row in self.orders.values():
                if row["status"] == "LIVE":
                    row["status"] = "CANCELED"

    def send(self):
        self.calls.append(("heartbeat", self.clock.seconds))
        if self.fail_heartbeat_at is not None and self.clock.seconds >= self.fail_heartbeat_at:
            raise ConnectionError("fixture heartbeat unavailable")
        self.last_heartbeat = self.clock.seconds
        return {"status": "ok"}

    def list_open_orders(self):
        self.advance()
        rows = [row for row in self.orders.values() if row["status"] == "LIVE"]
        self.calls.append(("open_orders", tuple(row["id"] for row in rows)))
        return Page(rows)

    def get_balance_allowance(self, **kwargs):
        return {"balance": self.cash, "allowances": {"fixture-exchange": "100000000"}}

    def get_closed_only_mode(self):
        return False

    def get_order_book(self, *, token_id):
        inputs = self.snapshot()["quote_inputs"]
        side = "yes" if token_id == TOKENS[0] else "no"
        return {"asset_id": token_id, "market": CONDITION, "min_order_size": "5", "tick_size": "0.01",
                "neg_risk": False, "bids": inputs[side + "_bids"], "asks": inputs[side + "_asks"]}

    def create_limit_order(self, **order):
        self.calls.append(("fake_sign", order["token_id"]))
        return {**order, "signer": MAKER, "maker": MAKER, "signature_type": 0,
                "signature": "0x" + "f" * 130, "order_type": "GTC"}

    def post_order(self, order):
        self.calls.append(("fake_submit", order["token_id"]))
        if self.reject_second and len(self.orders) == 1:
            raise RuntimeError("fixture second-leg rejection")
        oid = "fixture-order-" + str(len(self.orders) + 1)
        self.orders[oid] = {"id": oid, "asset_id": order["token_id"], "market": CONDITION,
                            "maker_address": MAKER, "side": "BUY", "price": str(order["price"]),
                            "original_size": str(order["size"]), "size_matched": "0",
                            "status": "LIVE", "associate_trades": []}
        return {"ok": True, "order_id": oid, "status": "live", "trade_ids": [], "transactions_hashes": []}

    def get_order(self, *, order_id):
        self.advance()
        return deepcopy(self.orders[order_id])

    def list_account_trades(self, **kwargs):
        self.advance()
        return Page([{"id": "fixture-fill"}] if any(o["size_matched"] != "0" for o in self.orders.values()) else [])

    def cancel_all(self):
        self.calls.append(("cancel_all", self.clock.seconds))
        if self.cancel_unavailable:
            raise ConnectionError("fixture cancel unavailable")
        canceled = []
        for row in self.orders.values():
            if row["status"] == "LIVE":
                row["status"] = "CANCELED"
                canceled.append(row["id"])
        return {"canceled": canceled, "not_canceled": {}}

    def snapshot(self, *, checkpoint=lambda: None):
        checkpoint()
        values = {
            "yes_bids": [{"price": ".34", "size": "100"}], "yes_asks": [{"price": ".35", "size": "100"}],
            "no_bids": [{"price": ".65", "size": "100"}], "no_asks": [{"price": ".66", "size": "100"}],
            "reward_min_size": "20", "reward_max_spread_cents": "4.5", "reward_rate_per_day": "54",
            "tick": ".01", "post_only_available": True,
        }
        for row in self.orders.values():
            if row["status"] == "LIVE":
                from decimal import Decimal
                side = "yes" if row["asset_id"] == TOKENS[0] else "no"
                opposite = "no" if side == "yes" else "yes"
                values[side + "_bids"].append({"price": row["price"], "size": row["original_size"]})
                values[opposite + "_asks"].append({"price": str(1 - Decimal(row["price"])), "size": row["original_size"]})
        if self.public_change and self.clock.seconds >= 60:
            self.public_change(values)
        rules = {token: {"tick_size": ".01", "min_order_size": "5", "fee_rate_bps": "0", "neg_risk": False} for token in TOKENS}
        return {"condition_id": CONDITION, "token_ids": list(TOKENS), "observed_at_utc": self.clock.now().isoformat(),
                "quote_inputs": values, "rules": rules}

    def geography(self):
        blocked = self.fail_geoblock_at is not None and self.clock.seconds >= self.fail_geoblock_at

        class Response:
            status = 200
            headers = {"Content-Type": "application/json"}
            def geturl(self):
                return "https://polymarket.com/api/geoblock"
            def read(self, _limit):
                return json.dumps({"blocked": blocked, "country": "US", "region": "", "ip": "203.0.113.1"}).encode()
            def close(self):
                pass

        return check_geographic_eligibility(
            self.geography_root / (str(self.clock.seconds) + '.json'),
            confirmation=PHYSICAL_LOCATION_CONFIRMATION, physical_location_eligible=True,
            no_circumvention=True, clock=self.clock.now, opener=lambda *_args, **_kwargs: Response(),
        )

    def positions(self):
        rows = []
        url = "https://data-api.polymarket.com/positions?" + urlencode(
            {"user": MAKER, "market": CONDITION, "sizeThreshold": 0, "limit": 500, "offset": 0})
        return {"status": "OBSERVED", "query_scope": "exact_maker_condition", "maker_address": MAKER,
                "condition_id": CONDITION, "http_status": 200, "response_sha256": "a" * 64,
                "request_url": url, "rows": rows}


def adapters_and_gates(root, clock, venue):
    numeric_authority_fixture(root, clock)
    venue.geography_root = root / 'geography'
    adapters, gates = [], []
    for token in TOKENS:
        adapter = OfficialPolymarketGlobalAdapter(
            venue, token_id=token, maker_address=MAKER, condition_id=CONDITION,
            user_event_reader=lambda: [], user_event_health_reader=lambda: {"state": "SUBSCRIPTION_PROVEN"},
            position_reader=venue.positions, heartbeat_sender=venue,
            market_rule_reader=lambda token=token: {"token_id": token, "tick_size": ".01", "neg_risk": False, "fee_rate_bps": "0"},
            sdk_version="0.6.0", authoritative_readers_verified=True,
            monotonic_clock=clock.monotonic, utc_clock=clock.now, sleeper=clock.sleep,
            envelope_profile_id=STAGE2_HOLD_V1.profile_id, envelope_authority_root=root, max_order_notional=16,
        )
        gate = {"required": True, "ok": True, "schema_version": "mm_platform_bootstrap_v0.6", "status": "PASS",
                "platform": "polymarket_global", "settlement_unit": "pUSD", "token_id": token,
                "condition_id": CONDITION, "funder_address": MAKER, "sdk_version": "0.6.0", "signature_type_id": 0,
                "isolated_pilot_wallet": True, "pilot_wallet_max_funding_usdc": 100,
                "requested_budget_usdc": 10, "account_snapshot_sha256": ("a" if token == TOKENS[0] else "b") * 64,
                "checks": {"all_bootstrap_checks": True}, "missing": []}
        adapters.append(adapter)
        gates.append(gate)
    return adapters, gates
