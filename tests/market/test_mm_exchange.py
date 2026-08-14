import csv
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from weather.market.mm_exchange import (  # noqa: E402
    PolymarketGlobalHTTPAdapter,
    PolymarketUSHTTPAdapter,
    RecordingTransport,
    build_adapter_request_plan,
    build_exchange_reconciliation,
    credential_diagnostics,
    lifecycle_events_from_user_events,
)
from weather.market.market_making_run_support import load_open_lifecycle_orders  # noqa: E402
from weather.market.mm_official_adapter import (  # noqa: E402
    OfficialPolymarketGlobalAdapter,
    exact_current_positions_evidence,
    fetch_current_positions,
    fetch_current_maker_rebates,
    normalize_official_user_event,
    require_official_clob_version,
)
from weather.market.mm_geoblock import collect_official_geoblock_evidence  # noqa: E402
from weather.market.mm_exchange_reports import confirmed_trade_set_sha256  # noqa: E402


NOW = "2026-06-14T16:00:00+00:00"


def geoblock_evidence(*, blocked=False, country="CH", region="ZH"):
    class Response:
        status = 200

        def read(self, _limit):
            return json.dumps({
                "blocked": blocked,
                "country": country,
                "region": region,
                "ip": "203.0.113.8",
            }).encode("utf-8")

        def close(self):
            pass

    return collect_official_geoblock_evidence(
        opener=lambda _request, timeout: Response(),
        proxy_detector=lambda: {},
    )


def eligible_geoblock():
    return geoblock_evidence()


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def append_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def read_csv(path):
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def official_stage1_gate(adapter, snapshot_character="b"):
    return {
        "required": True,
        "ok": True,
        "schema_version": "mm_platform_bootstrap_v0.1",
        "status": "PASS",
        "platform": "polymarket_global",
        "settlement_unit": "pUSD",
        "condition_id": adapter.condition_id,
        "token_id": adapter.token_id,
        "funder_address": adapter.maker_address,
        "sdk_version": adapter.sdk_version,
        "signature_type_id": 3,
        "requested_budget_usdc": 100.0,
        "account_snapshot_sha256": snapshot_character * 64,
        "geoblock_country": "CH",
        "geoblock_region": "ZH",
        "geoblock_evidence_sha256": "e" * 64,
        "checks": {"all_bootstrap_checks": True},
        "missing": [],
    }


def write_csv(path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_run_folder(
    root,
    preflight_status="PASS",
    *,
    release_production_capable=True,
):
    run_folder = root / "mm_runs" / "2026-06-14" / "exchange-run"
    run_folder.mkdir(parents=True)
    run_config = {
        "schema_version": "mm_run_v0.2",
        "run_id": "exchange-run",
        "target_date": "2026-06-14",
        "mode": "live-pilot",
        "budget_usdc": 25.0,
        "markets": ["atlanta"],
    }
    preflight = {
        "schema_version": "mm_run_v0.2",
        "run_id": "exchange-run",
        "target_date": "2026-06-14",
        "mode": "live-pilot",
        "status": preflight_status,
        "release_production_capable": release_production_capable,
        "live_readiness": {"ok": preflight_status == "PASS"},
        "data_layer_live_gate": {"ok": preflight_status == "PASS"},
        "platform_verification_gate": {
            "ok": preflight_status == "PASS",
            "platform": "polymarket_us",
            "path": "platform.json",
            "market_slug": "highest-temperature-in-atlanta-on-june-14-2026",
        },
        "markets": [{
            "market_id": "atlanta",
            "event_slug": "highest-temperature-in-atlanta-on-june-14-2026",
            "status": preflight_status,
        }],
    }
    write_json(run_folder / "run_config.json", run_config)
    write_json(run_folder / "preflight.json", preflight)
    write_csv(
        run_folder / "quote_intents_long.csv",
        [
            "run_id",
            "quote_permission",
            "expected_rebate_value",
            "expected_reward_score",
            "market_id",
            "event_slug",
            "range_label",
        ],
        [{
            "run_id": "exchange-run",
            "quote_permission": "True",
            "expected_rebate_value": "0.01",
            "expected_reward_score": "0.25",
            "market_id": "atlanta",
            "event_slug": "highest-temperature-in-atlanta-on-june-14-2026",
            "range_label": "80-81 F",
        }],
    )
    append_jsonl(
        run_folder / "order_lifecycle.jsonl",
        [{
            "schema_version": "mm_run_v0.2",
            "run_id": "exchange-run",
            "generated_at_utc": NOW,
            "posted_at_utc": NOW,
            "transition": "live_posted",
            "lifecycle_key": "life-1",
            "order_key": "order-1",
            "market_id": "atlanta",
            "event_slug": "highest-temperature-in-atlanta-on-june-14-2026",
            "range_label": "80-81 F",
            "clob_token_id": "token-80",
            "side": "YES_BID",
            "price": 0.49,
            "size": 5.0,
            "remaining_size": 5.0,
            "open_risk_usdc": 2.45,
            "remaining_risk_usdc": 2.45,
        }],
    )
    return run_folder


class TestMMExchange(unittest.TestCase):
    def test_official_maker_trade_is_exact_scope_filtered_and_booked_only_when_confirmed(self):
        maker_address = "0x" + "a" * 40
        condition_id = "0x" + "b" * 64
        token_id = "12345"
        raw = {
            "event_type": "trade",
            "id": "trade-1",
            "market": condition_id,
            "asset_id": token_id,
            "status": "MATCHED",
            "trader_side": "MAKER",
            "maker_address": "0x" + "e" * 40,
            "transaction_hash": "",
            "match_time": "1781452801",
            "maker_orders": [
                {
                    "order_id": "other-order",
                    "maker_address": "0x" + "c" * 40,
                    "asset_id": token_id,
                    "matched_amount": "9",
                    "price": "0.49",
                    "fee_rate_bps": "0",
                    "side": "BUY",
                },
                {
                    "order_id": "order-1",
                    "maker_address": maker_address,
                    "asset_id": token_id,
                    "matched_amount": "2",
                    "price": "0.49",
                    "fee_rate_bps": "0",
                    "side": "BUY",
                },
            ],
        }

        pending = normalize_official_user_event(
            raw,
            maker_address=maker_address,
            condition_id=condition_id,
            token_id=token_id,
        )
        confirmed = normalize_official_user_event(
            {
                **raw,
                "status": "CONFIRMED",
                "transaction_hash": "0x" + "d" * 64,
            },
            maker_address=maker_address,
            condition_id=condition_id,
            token_id=token_id,
        )
        events, fills = lifecycle_events_from_user_events(
            pending + confirmed,
            datetime.fromisoformat(NOW),
            exchange_order_to_lifecycle={"order-1": "life-1"},
        )

        self.assertEqual(pending[0]["event_type"], "trade_pending")
        self.assertEqual(pending[0]["order_id"], "order-1")
        self.assertEqual(pending[0]["maker_address"], maker_address)
        self.assertEqual(pending[0]["exchange_match_time"], "1781452801")
        self.assertEqual([row["transition"] for row in events], ["fill_pending", "filled"])
        self.assertEqual(len(fills), 1)
        self.assertEqual(fills[0]["lifecycle_key"], "life-1")
        self.assertEqual(fills[0]["liquidity_role"], "MAKER")
        self.assertEqual(fills[0]["official_trade_status"], "CONFIRMED")
        self.assertEqual(fills[0]["transaction_hash"], "0x" + "d" * 64)

        class NormalizedReaderClient:
            def get_open_orders(self):
                return []

        normalized_adapter = OfficialPolymarketGlobalAdapter(
            NormalizedReaderClient(),
            token_id=token_id,
            user_event_reader=lambda: confirmed,
            user_event_health_reader=lambda: {"state": "SUBSCRIPTION_PROVEN"},
            position_reader=lambda: [],
            maker_address=maker_address,
            condition_id=condition_id,
            authoritative_readers_verified=True,
            sdk_version="1.1.0",
        )
        self.assertEqual(normalized_adapter.user_events(), confirmed)

        canceled = normalize_official_user_event(
            {
                "event_type": "order",
                "id": "order-1",
                "market": condition_id,
                "asset_id": token_id,
                "type": "CANCELLATION",
                "status": "CANCELED",
                "maker_address": maker_address,
            },
            maker_address=maker_address,
            condition_id=condition_id,
            token_id=token_id,
        )
        self.assertEqual(canceled[0]["event_type"], "canceled")
        self.assertEqual(canceled[0]["order_id"], "order-1")

    def test_public_maker_rebate_reader_validates_exact_response_scope(self):
        maker_address = "0x" + "a" * 40
        condition_id = "0x" + "b" * 64
        asset_address = "0x" + "c" * 40
        captured = {}

        class Response:
            def read(self):
                return json.dumps([{
                    "date": "2026-08-13",
                    "condition_id": condition_id,
                    "asset_address": asset_address,
                    "maker_address": maker_address,
                    "rebated_fees_usdc": "1.237519",
                }]).encode("utf-8")

            def close(self):
                captured["closed"] = True

        def opener(request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            return Response()

        rows = fetch_current_maker_rebates(
            maker_address,
            "2026-08-13",
            opener=opener,
        )

        self.assertEqual(rows[0]["condition_id"], condition_id)
        self.assertEqual(rows[0]["rebated_fees_usdc"], "1.237519")
        self.assertIn("date=2026-08-13", captured["url"])
        self.assertIn("maker_address=", captured["url"])
        self.assertTrue(captured["closed"])

        evidence = fetch_current_maker_rebates(
            maker_address,
            "2026-08-13",
            opener=opener,
            return_evidence=True,
            now="2026-08-14T01:00:00+00:00",
        )
        self.assertEqual(evidence["query_scope"], "exact_maker_date")
        self.assertEqual(evidence["queried_at_utc"], "2026-08-14T01:00:00+00:00")
        self.assertEqual(len(evidence["response_sha256"]), 64)

    def test_public_position_reader_binds_empty_result_to_exact_scope(self):
        maker_address = "0x" + "a" * 40
        condition_id = "0x" + "b" * 64
        captured = {}

        class Response:
            status = 200

            def read(self):
                return b"[]"

            def close(self):
                captured["closed"] = True

        def opener(request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            return Response()

        evidence = fetch_current_positions(
            maker_address,
            condition_id,
            opener=opener,
        )

        self.assertEqual(evidence["status"], "OBSERVED")
        self.assertEqual(evidence["query_scope"], "exact_maker_condition")
        self.assertEqual(evidence["rows"], [])
        self.assertEqual(len(evidence["response_sha256"]), 64)
        self.assertIn("user=0x", captured["url"])
        self.assertIn("market=0x", captured["url"])
        self.assertIn("limit=500", captured["url"])
        self.assertIn("offset=0", captured["url"])
        self.assertTrue(exact_current_positions_evidence(
            evidence,
            maker_address=maker_address,
            condition_id=condition_id,
            rows=[],
        ))
        evidence["request_url"] += "&limit=1"
        self.assertFalse(exact_current_positions_evidence(
            evidence,
            maker_address=maker_address,
            condition_id=condition_id,
            rows=[],
        ))
        self.assertTrue(captured["closed"])

    def test_official_global_adapter_is_pinned_and_reconciliation_complete_before_mutation(self):
        class FakeClient:
            def __init__(self):
                self.calls = []
                self.open_orders = []
                self.heartbeat_counter = 0
                self.signed_maker = "0x" + "a" * 40
                self.signed_signer = None
                self.signature_type = 3
                self.book_asset_id = "token-80"
                self.book_condition_id = "0x" + "b" * 64
                self.next_order_response = {
                    "success": True,
                    "orderID": "order-1",
                    "status": "live",
                    "tradeIDs": [],
                    "transactionsHashes": [],
                }

            def get_open_orders(self):
                self.calls.append(("get_open_orders",))
                return list(self.open_orders)

            def get_address(self):
                return "0x" + "d" * 40

            def get_balance_allowance(self, *, params):
                self.calls.append(("get_balance_allowance", params))
                return {"balance": "100", "allowances": {"exchange": "100"}}

            def get_current_rewards(self):
                return [{"condition_id": "condition-1"}]

            def get_fee_rate_bps(self, token_id):
                return 50 if token_id == "token-80" else 0

            def get_closed_only_mode(self):
                return {"closed_only": False}

            def get_order_book(self, token_id):
                self.calls.append(("get_order_book", token_id))
                return {
                    "asset_id": self.book_asset_id,
                    "market": self.book_condition_id,
                    "min_order_size": "5",
                    "tick_size": "0.01",
                    "neg_risk": False,
                    "bids": [{"price": "0.49", "size": "10"}],
                    "asks": [{"price": "0.51", "size": "10"}],
                }

            def get_tick_size(self, token_id):
                self.calls.append(("get_tick_size", token_id))
                return "0.01"

            def post_heartbeat(self, heartbeat_id):
                self.calls.append(("post_heartbeat", heartbeat_id))
                self.heartbeat_counter += 1
                return {"heartbeat_id": f"hb-{self.heartbeat_counter}"}

            def create_order(self, order, *, options):
                self.calls.append(("create_order", order, options))
                return {
                    "signer": self.signed_signer or (
                        self.signed_maker
                        if self.signature_type == 3
                        else self.get_address()
                    ),
                    "maker": self.signed_maker,
                    "tokenId": order["token_id"],
                    "signatureType": self.signature_type,
                    "signature": "0x" + "f" * 130,
                }

            def post_order(self, signed_order, *, order_type, post_only):
                self.calls.append(("post_order", signed_order, order_type, post_only))
                return dict(self.next_order_response)

            def get_order(self, order_id):
                return {"id": order_id}

            def cancel_order(self, payload):
                self.calls.append(("cancel_order", payload))
                return {"canceled": payload["orderID"]}

            def cancel_all(self):
                self.calls.append(("cancel_all",))
                self.open_orders = []
                return {"canceled": True}

        with self.assertRaisesRegex(RuntimeError, "observed 1.0.0"):
            require_official_clob_version("1.0.0")

        client = FakeClient()
        read_only = OfficialPolymarketGlobalAdapter(client, sdk_version="1.1.0")
        self.assertFalse(read_only.supports_trading)
        with self.assertRaisesRegex(RuntimeError, "verified authoritative user-event"):
            read_only.place_order({"token_id": "token-80", "price": 0.49, "size": 5, "side": "BUY"})

        unverified = OfficialPolymarketGlobalAdapter(
            client,
            user_event_reader=lambda: [],
            position_reader=lambda: [],
            sdk_version="1.1.0",
        )
        self.assertFalse(unverified.supports_trading)

        clock = [100.0]

        class FakeOrderType:
            GTC = "GTC"

        def make_adapter(bound_client):
            return OfficialPolymarketGlobalAdapter(
                bound_client,
                token_id="token-80",
                user_event_reader=lambda: [{"event_type": "order", "id": "order-1"}],
                user_event_health_reader=lambda: {"state": "SUBSCRIPTION_PROVEN"},
                position_reader=lambda: [{"asset": "token-80", "size": "5"}],
                rebate_reader=lambda: [{
                    "date": "2026-08-13",
                    "condition_id": "0x" + "b" * 64,
                    "asset_address": "0x" + "c" * 40,
                    "maker_address": "0x" + "a" * 40,
                    "rebated_fees_usdc": "1.25",
                }],
                rebate_date="2026-08-13",
                maker_address="0x" + "a" * 40,
                condition_id="0x" + "b" * 64,
                rebate_payout_cycle_complete=True,
                order_args_factory=lambda **kwargs: kwargs,
                order_payload_factory=lambda **kwargs: kwargs,
                order_type_factory=FakeOrderType,
                order_options_factory=lambda **kwargs: kwargs,
                collateral_balance_params={"asset_type": "COLLATERAL"},
                sdk_version="1.1.0",
                authoritative_readers_verified=True,
                monotonic_clock=lambda: clock[0],
                geoblock_checker=eligible_geoblock,
            )

        adapter = make_adapter(client)
        self.assertTrue(adapter.supports_trading)
        with self.assertRaisesRegex(RuntimeError, "acknowledged heartbeat"):
            adapter.place_order({
                "token_id": "token-80",
                "price": 0.49,
                "size": 5,
                "side": "BUY",
            })
        self.assertEqual(adapter.heartbeat(), {"heartbeat_id": "hb-1"})
        with self.assertRaisesRegex(RuntimeError, "fresh market-rules snapshot"):
            adapter.place_order({
                "token_id": "token-80",
                "price": 0.49,
                "size": 5,
                "side": "BUY",
            })
        market_rules = adapter.refresh_market_rules()
        self.assertEqual(market_rules["condition_id"], "0x" + "b" * 64)
        self.assertEqual(market_rules["tick_size"], "0.01")
        self.assertEqual(market_rules["best_ask"], "0.51")
        preview = adapter.preview_signed_order(
            {
                "token_id": "token-80",
                "price": 0.01,
                "size": 5,
                "side": "BUY",
            },
            expected_signature_type_id=3,
        )
        self.assertEqual(preview["status"], "VERIFIED_NON_POSTING_PREVIEW")
        self.assertFalse(preview["signature_retained"])
        self.assertNotIn("signature", preview)
        self.assertEqual(preview["client_signer_address"], "0x" + "d" * 40)
        self.assertEqual(preview["order_signer_address"], "0x" + "a" * 40)
        self.assertEqual(len(preview["signed_order_sha256"]), 64)

        missing_book_token_client = FakeClient()
        missing_book_token_client.book_asset_id = ""
        with self.assertRaisesRegex(RuntimeError, "order-book token differs"):
            make_adapter(missing_book_token_client).refresh_market_rules()

        wrong_book_condition_client = FakeClient()
        wrong_book_condition_client.book_condition_id = "0x" + "c" * 64
        with self.assertRaisesRegex(RuntimeError, "order-book condition differs"):
            make_adapter(wrong_book_condition_client).refresh_market_rules()

        safe_client = FakeClient()
        safe_client.signature_type = 2
        safe_adapter = make_adapter(safe_client)
        safe_adapter.refresh_market_rules()
        safe_preview = safe_adapter.preview_signed_order(
            {
                "token_id": "token-80",
                "price": 0.01,
                "size": 5,
                "side": "BUY",
            },
            expected_signature_type_id=2,
        )
        self.assertEqual(safe_preview["client_signer_address"], "0x" + "d" * 40)
        self.assertEqual(safe_preview["order_signer_address"], "0x" + "d" * 40)
        self.assertEqual(safe_preview["maker_address"], "0x" + "a" * 40)

        eoa_order_signer_client = FakeClient()
        eoa_order_signer_client.signed_signer = eoa_order_signer_client.get_address()
        eoa_order_signer_adapter = make_adapter(eoa_order_signer_client)
        eoa_order_signer_adapter.refresh_market_rules()
        with self.assertRaisesRegex(
            RuntimeError,
            "order_signer_matches_wallet_topology",
        ):
            eoa_order_signer_adapter.preview_signed_order(
                {
                    "token_id": "token-80",
                    "price": 0.01,
                    "size": 5,
                    "side": "BUY",
                },
                expected_signature_type_id=3,
            )
        valid_intent = {
            "token_id": "token-80",
            "price": 0.49,
            "size": 5,
            "side": "BUY",
        }
        closed_only_client = FakeClient()
        closed_only_client.get_closed_only_mode = lambda: True
        closed_only_adapter = make_adapter(closed_only_client)
        closed_only_adapter.heartbeat()
        closed_only_adapter.refresh_market_rules()
        with self.assertRaisesRegex(RuntimeError, "account is in closed-only mode"):
            closed_only_adapter.place_order(valid_intent)
        self.assertFalse(any(
            call[0] == "post_order"
            for call in closed_only_client.calls
        ))

        malformed_closed_only_client = FakeClient()
        malformed_closed_only_client.get_closed_only_mode = lambda: None
        malformed_closed_only_adapter = make_adapter(malformed_closed_only_client)
        malformed_closed_only_adapter.heartbeat()
        malformed_closed_only_adapter.refresh_market_rules()
        with self.assertRaisesRegex(RuntimeError, "authoritative boolean"):
            malformed_closed_only_adapter.place_order(valid_intent)
        self.assertFalse(any(
            call[0] == "post_order"
            for call in malformed_closed_only_client.calls
        ))

        blocked_adapter = make_adapter(FakeClient())
        blocked_adapter.geoblock_checker = lambda: geoblock_evidence(
            blocked=True,
            country="CA",
            region="ON",
        )
        with self.assertRaisesRegex(RuntimeError, "geoblock proof blocks order mutation"):
            blocked_adapter.authorize_stage1_lifecycle(
                official_stage1_gate(blocked_adapter)
            )

        route_changed_adapter = make_adapter(FakeClient())
        route_changed_adapter.heartbeat()
        route_changed_adapter.refresh_market_rules()
        route_capability = route_changed_adapter.authorize_stage1_lifecycle(
            official_stage1_gate(route_changed_adapter, snapshot_character="f")
        )
        route_changed_adapter.geoblock_checker = lambda: geoblock_evidence(
            blocked=True,
            country="CA",
            region="ON",
        )
        with self.assertRaisesRegex(RuntimeError, "geoblock proof blocks order mutation"):
            route_changed_adapter.place_order(
                valid_intent,
                stage1_capability=route_capability,
            )
        self.assertTrue(route_changed_adapter.diagnostics()["stage1_capability_consumed"])
        self.assertFalse(any(
            call[0] == "post_order"
            for call in route_changed_adapter.client.calls
        ))

        wrong_signer_client = FakeClient()
        wrong_signer_client.signed_maker = "0x" + "e" * 40
        wrong_signer_adapter = make_adapter(wrong_signer_client)
        wrong_signer_adapter.heartbeat()
        wrong_signer_adapter.refresh_market_rules()
        wrong_signer_capability = wrong_signer_adapter.authorize_stage1_lifecycle(
            official_stage1_gate(wrong_signer_adapter, snapshot_character="1")
        )
        with self.assertRaisesRegex(RuntimeError, "signed-order identity mismatch"):
            wrong_signer_adapter.place_order(
                valid_intent,
                stage1_capability=wrong_signer_capability,
            )
        self.assertFalse(any(
            call[0] == "post_order"
            for call in wrong_signer_client.calls
        ))

        malformed_signature_client = FakeClient()
        malformed_signature_client.signature_type = 2
        original_create_order = malformed_signature_client.create_order

        def create_malformed_order(order, *, options):
            signed = original_create_order(order, options=options)
            signed["signature"] = "present-but-not-an-eip-signature"
            return signed

        malformed_signature_client.create_order = create_malformed_order
        malformed_signature_adapter = make_adapter(malformed_signature_client)
        malformed_signature_adapter.refresh_market_rules()
        with self.assertRaisesRegex(RuntimeError, "signature_valid"):
            malformed_signature_adapter.preview_signed_order(
                {
                    "token_id": "token-80",
                    "price": 0.01,
                    "size": 5,
                    "side": "BUY",
                },
                expected_signature_type_id=2,
            )

        malformed_heartbeat_client = FakeClient()
        malformed_heartbeat_client.post_heartbeat = lambda _heartbeat_id: {
            "heartbeat_id": 123,
        }
        with self.assertRaisesRegex(RuntimeError, "nonempty string heartbeat id"):
            make_adapter(malformed_heartbeat_client).heartbeat()

        repeated_heartbeat_client = FakeClient()
        repeated_heartbeat_client.post_heartbeat = lambda _heartbeat_id: {
            "heartbeat_id": "hb-static",
        }
        repeated_heartbeat_adapter = make_adapter(repeated_heartbeat_client)
        repeated_heartbeat_adapter.heartbeat()
        with self.assertRaisesRegex(RuntimeError, "nonempty string heartbeat id"):
            repeated_heartbeat_adapter.heartbeat()

        stopped_stream_client = FakeClient()
        stopped_stream_adapter = make_adapter(stopped_stream_client)
        stopped_stream_adapter.heartbeat()
        stopped_stream_adapter.refresh_market_rules()
        stopped_stream_capability = stopped_stream_adapter.authorize_stage1_lifecycle(
            official_stage1_gate(stopped_stream_adapter, snapshot_character="2")
        )
        stopped_stream_adapter.user_event_health_reader = lambda: {"state": "FAILED"}
        with self.assertRaisesRegex(RuntimeError, "user-event stream is not active"):
            stopped_stream_adapter.place_order(
                valid_intent,
                stage1_capability=stopped_stream_capability,
            )
        self.assertFalse(any(
            call[0] == "post_order"
            for call in stopped_stream_client.calls
        ))

        with self.assertRaisesRegex(RuntimeError, "Stage 1 lifecycle capability"):
            adapter.place_order(valid_intent)
        capability = adapter.authorize_stage1_lifecycle(official_stage1_gate(adapter))
        response = adapter.place_order(valid_intent, stage1_capability=capability)
        self.assertTrue(response["success"])
        post_call = next(call for call in client.calls if call[0] == "post_order")
        self.assertEqual(post_call[2:], ("GTC", True))
        create_calls = [call for call in client.calls if call[0] == "create_order"]
        self.assertEqual(create_calls[-1][1]["token_id"], "token-80")

        with self.assertRaisesRegex(RuntimeError, "below the current market minimum"):
            adapter.place_order({
                "token_id": "token-80",
                "price": 0.49,
                "size": 4.99,
                "side": "BUY",
            })
        with self.assertRaisesRegex(RuntimeError, "current market tick size"):
            adapter.place_order({
                "token_id": "token-80",
                "price": 0.495,
                "size": 5,
                "side": "BUY",
            })
        with self.assertRaisesRegex(RuntimeError, "adapter pilot cap"):
            adapter.place_order({
                "token_id": "token-80",
                "price": 0.49,
                "size": 21,
                "side": "BUY",
            })
        with self.assertRaisesRegex(RuntimeError, "cross the fresh best ask"):
            adapter.place_order({
                "token_id": "token-80",
                "price": 0.51,
                "size": 5,
                "side": "BUY",
            })

        with self.assertRaisesRegex(RuntimeError, "verified owned outcome inventory"):
            adapter.place_order({
                "token_id": "token-80",
                "price": 0.51,
                "size": 5,
                "side": "SELL",
            })
        with self.assertRaisesRegex(RuntimeError, "exceeds authoritative owned"):
            adapter.place_order({
                "token_id": "token-80",
                "price": 0.51,
                "size": 5.01,
                "side": "SELL",
                "owned_inventory_verified": True,
            })
        with self.assertRaisesRegex(RuntimeError, "single allowed token"):
            adapter.place_order({
                "token_id": "different-token",
                "price": 0.49,
                "size": 5,
                "side": "BUY",
            })

        unsafe_client = FakeClient()
        unsafe_client.next_order_response = {
            "success": True,
            "orderID": "order-unsafe",
            "status": "matched",
            "tradeIDs": ["trade-1"],
        }
        unsafe_adapter = make_adapter(unsafe_client)
        unsafe_adapter.heartbeat()
        unsafe_adapter.refresh_market_rules()
        unsafe_capability = unsafe_adapter.authorize_stage1_lifecycle(
            official_stage1_gate(unsafe_adapter, snapshot_character="d")
        )
        with self.assertRaisesRegex(RuntimeError, "execution-free live order"):
            unsafe_adapter.place_order(
                valid_intent,
                stage1_capability=unsafe_capability,
            )
        self.assertTrue(
            unsafe_adapter.probe_evidence()["cancel_all_zero_open_orders_verified"]
        )

        malformed_success_client = FakeClient()
        malformed_success_client.next_order_response["success"] = "false"
        malformed_success_adapter = make_adapter(malformed_success_client)
        malformed_success_adapter.heartbeat()
        malformed_success_adapter.refresh_market_rules()
        malformed_success_capability = (
            malformed_success_adapter.authorize_stage1_lifecycle(
                official_stage1_gate(
                    malformed_success_adapter,
                    snapshot_character="e",
                )
            )
        )
        with self.assertRaisesRegex(RuntimeError, "execution-free live order"):
            malformed_success_adapter.place_order(
                valid_intent,
                stage1_capability=malformed_success_capability,
            )
        self.assertTrue(
            malformed_success_adapter.probe_evidence()[
                "cancel_all_zero_open_orders_verified"
            ]
        )

        with self.assertRaisesRegex(RuntimeError, "heartbeat id does not continue"):
            adapter.heartbeat("stale-id")
        self.assertEqual(adapter.heartbeat(), {"heartbeat_id": "hb-2"})
        clock[0] += 8
        with self.assertRaisesRegex(RuntimeError, "fresh heartbeat"):
            adapter.place_order({
                "token_id": "token-80",
                "price": 0.49,
                "size": 5,
                "side": "BUY",
            })

        self.assertEqual(adapter.balances()["balance"], "100")
        self.assertEqual(adapter.allowances(), {"exchange": "100"})
        self.assertEqual(
            sum(1 for call in client.calls if call[0] == "get_balance_allowance"),
            1,
        )
        collateral_evidence = adapter.refresh_collateral_evidence()
        self.assertEqual(collateral_evidence["balance_atomic"], "100")
        self.assertEqual(collateral_evidence["allowances_atomic"], {"exchange": "100"})
        self.assertEqual(len(collateral_evidence["response_sha256"]), 64)
        self.assertEqual(
            sum(1 for call in client.calls if call[0] == "get_balance_allowance"),
            2,
        )
        self.assertEqual(adapter.fees()["fee_rate_bps"], 50)
        self.assertEqual(
            adapter.rewards()["maker_rebate_evidence"]["rows"][0]["rebated_fees_usdc"],
            "1.25",
        )
        adapter.cancel_all()
        self.assertTrue(adapter.probe_evidence()["cancel_all_zero_open_orders_verified"])
        self.assertTrue(adapter.diagnostics()["secret_values_redacted"])

    def test_fixture_reconciliation_appends_lifecycle_fills_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_folder = write_run_folder(root)
            user_event = {
                "event_type": "fill",
                "generated_at_utc": "2026-06-14T16:00:30+00:00",
                "lifecycle_key": "life-1",
                "order_id": "ex-1",
                "run_id": "exchange-run",
                "market_id": "atlanta",
                "event_slug": "highest-temperature-in-atlanta-on-june-14-2026",
                "range_label": "80-81 F",
                "maker_address": "0x" + "a" * 40,
                "condition_id": "0x" + "b" * 64,
                "clob_token_id": "token-80",
                "side": "YES_BID",
                "fill_price": 0.49,
                "fill_size": 2.0,
                "trade_id": "trade-1",
                "transaction_hash": "0x" + "d" * 64,
                "liquidity_role": "MAKER",
                "fee_rate_bps": 500,
                "official_trade_status": "CONFIRMED",
                "markout_30m": 0.02,
                "maker_rebate_estimate_usdc": 0.01,
            }
            _, expected_fills = lifecycle_events_from_user_events(
                [user_event],
                datetime.fromisoformat(NOW),
            )
            fixture = write_json(root / "exchange_fixture.json", {
                "open_orders": [{
                    "lifecycle_key": "life-1",
                    "order_id": "ex-1",
                    "status": "live",
                    "remaining_size": 3.0,
                }],
                "user_events": [user_event],
                "balances": {
                    "starting_cash_usdc": 25.0,
                    "ending_cash_usdc": 26.0,
                },
                "allowances": {"pUSD": 25.0},
                "positions": [],
                "position_evidence": {
                    "status": "OBSERVED",
                    "query_scope": "exact_maker_condition",
                    "maker_address": "0x" + "a" * 40,
                    "condition_id": "0x" + "b" * 64,
                    "rows": [],
                    "http_status": 200,
                    "response_sha256": "f" * 64,
                    "request_url": (
                        "https://data-api.polymarket.com/positions?user=0x"
                        + "a" * 40
                        + "&market=0x"
                        + "b" * 64
                        + "&sizeThreshold=0&limit=500&offset=0"
                    ),
                },
                "rewards": {
                    "maker_rebate_evidence": {
                        "status": "OBSERVED",
                        "query_scope": "exact_maker_date",
                        "http_status": 200,
                        "response_sha256": "e" * 64,
                        "request_url": (
                            "https://clob.polymarket.com/rebates/current?"
                            "date=2026-06-14&maker_address=0x" + "a" * 40
                        ),
                        "query_date": "2026-06-14",
                        "queried_at_utc": "2026-06-15T01:00:00+00:00",
                        "maker_address": "0x" + "a" * 40,
                        "condition_id": "0x" + "b" * 64,
                        "payout_cycle_complete": True,
                        "rows": [{
                            "date": "2026-06-14",
                            "maker_address": "0x" + "a" * 40,
                            "condition_id": "0x" + "b" * 64,
                            "asset_address": "0x" + "c" * 40,
                            "rebated_fees_usdc": 0.01,
                        }],
                    },
                },
                "fees": {
                    "actual_fee_evidence": {
                        "status": "OBSERVED",
                        "coverage": "all_pilot_trades_and_exits",
                        "includes_taker_and_flattening_fees": True,
                        "calculation_basis": "confirmed_trade_events",
                        "fee_formula": "shares_x_rate_x_price_x_one_minus_price",
                        "maker_fees_zero": True,
                        "precision_decimal_places": 5,
                        "confirmed_trade_set_sha256": confirmed_trade_set_sha256(
                            expected_fills
                        ),
                        "maker_address": "0x" + "a" * 40,
                        "condition_id": "0x" + "b" * 64,
                        "observed_fill_count": 1,
                        "paid_usdc": 0.0,
                    },
                },
                "redemption_status": {
                    "redeemed": True,
                    "redemption_usdc": 1.0,
                    "settlement_pnl_usdc": 0.99,
                    "financial_identity": {
                        "external_cash_flows_usdc": 0.0,
                        "ending_positions_zero": True,
                        "settlement_pnl_excludes_fees_and_incentives": True,
                    },
                },
                "probe_evidence": {
                    "heartbeat_dead_man": {"passed": True, "detail": "throwaway order canceled by heartbeat lapse"},
                    "min_size_tick_post_only": {"passed": True, "detail": "preview rejected invalid tick and post-only cross"},
                    "cancel_all_verification": {
                        "passed": True,
                        "cancel_all_sent": True,
                        "cancel_all_response": {"canceledOrderIds": ["ex-1"]},
                        "open_order_count_after": 0,
                        "detail": "open-order query returned zero after cancel-all",
                    },
                },
            })

            payload = build_exchange_reconciliation(
                run_folder,
                execution_mode="read-only",
                fixture_path=fixture,
                append_reconciliation=True,
                now=NOW,
                env={
                    "POLYMARKET_US_KEY_ID": "key-id",
                    "POLYMARKET_US_SECRET_KEY_STORAGE_REF": "vault://pm/us",
                },
            )

            lifecycle = load_open_lifecycle_orders(run_folder / "order_lifecycle.jsonl")
            fills = read_csv(run_folder / "fills_long.csv")
            budget_events = [
                json.loads(line)
                for line in (run_folder / "budget_ledger.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            risk_events = [
                json.loads(line)
                for line in (run_folder / "risk_events.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            report_exists = Path(payload["report_path"]).exists()
            report_text = Path(payload["report_path"]).read_text(encoding="utf-8")
            probe = json.loads(Path(payload["mm2_probe_status_path"]).read_text(encoding="utf-8"))
            pilot_report = json.loads(Path(payload["pilot_report_json_path"]).read_text(encoding="utf-8"))
            pilot_report_exists = Path(payload["pilot_report_path"]).exists()

        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["matched_order_count"], 1)
        self.assertEqual(payload["user_stream_event_count"], 1)
        request_diagnostics = payload["adapter_request_diagnostics"]
        capability = request_diagnostics["capability_matrix"]
        cancel_batch_note = next(
            row for row in request_diagnostics["live_readiness_notes"]
            if row["code"] == "cancel_batch_size_limit"
        )
        note_codes = {row["code"] for row in request_diagnostics["live_readiness_notes"]}
        self.assertIn("create_post_only", capability["supported_actions"])
        self.assertEqual(capability["maker_only_order_field"], "participateDontInitiate")
        self.assertTrue(capability["requires_private_user_stream_for_final_order_state"])
        self.assertTrue(capability["requires_cancel_all_zero_open_orders_verification"])
        self.assertTrue(capability["batched_order_results_require_stream_confirmation"])
        self.assertEqual(capability["max_cancel_order_batch_size"], 20)
        self.assertTrue(capability["latency_stopgap_rejects_order_submit"])
        self.assertTrue(capability["latency_stopgap_cancel_exempt"])
        self.assertIn("private_user_stream_required", note_codes)
        self.assertIn("cancel_all_requires_zero_open_orders_confirmation", note_codes)
        self.assertIn("cancel_batch_size_limit", note_codes)
        self.assertIn("20 orders", cancel_batch_note["detail"])
        self.assertIn("private order stream", cancel_batch_note["detail"])
        self.assertIn("latency_stopgap_reject_handling_required", note_codes)
        self.assertGreater(payload["adapter_request_diagnostics"]["blocked_plan_count"], 0)
        self.assertEqual(probe["probe_status"]["heartbeat_dead_man"]["status"], "observed")
        self.assertEqual(probe["probe_status"]["min_size_tick_post_only"]["status"], "observed")
        self.assertEqual(probe["probe_status"]["cancel_all_verification"]["status"], "observed")
        self.assertTrue(pilot_report["evidence_complete"])
        self.assertAlmostEqual(float(pilot_report["markout_30m_mean"]), 0.02)
        self.assertTrue(pilot_report["financial_reconciliation_complete"])
        self.assertAlmostEqual(
            pilot_report["financial_reconciliation"]["actual_total_pnl_after_fees_incentives_usdc"],
            1.0,
        )
        self.assertEqual(pilot_report["financial_reconciliation"]["missing_evidence"], [])
        self.assertTrue(pilot_report_exists)
        self.assertIn("life-1", lifecycle)
        self.assertAlmostEqual(float(lifecycle["life-1"]["remaining_size"]), 3.0)
        self.assertEqual(fills[0]["fill_status"], "filled")
        self.assertEqual(budget_events[0]["event"], "exchange_filled")
        self.assertTrue(any(row.get("category") == "exchange_reconciliation" for row in risk_events))
        self.assertTrue(report_exists)
        self.assertIn("## Live Readiness Notes", report_text)
        self.assertIn("private_user_stream_required", report_text)
        self.assertIn("latency_stopgap_reject_handling_required", report_text)

    def test_global_heartbeat_uses_v1_endpoint(self):
        plan = build_adapter_request_plan(
            "polymarket_global",
            "heartbeat",
            metadata={"heartbeat_id": "hb-1"},
            signer=lambda message: b"signed",
            timestamp_ms="1234",
        )

        self.assertEqual(plan["method"], "POST")
        self.assertEqual(plan["path"], "/v1/heartbeats")
        self.assertEqual(plan["body"], {"heartbeat_id": "hb-1"})
        self.assertTrue(plan["ready"])

    def test_polymarket_us_private_ws_events_map_to_lifecycle_rows(self):
        now = datetime.fromisoformat(NOW)
        base_order = {
            "id": "ex-1",
            "clientOrderId": "life-1",
            "marketSlug": "highest-temperature-in-atlanta-on-june-14-2026",
            "marketMetadata": {"eventSlug": "highest-temperature-in-atlanta-on-june-14-2026"},
            "intent": "ORDER_INTENT_BUY_LONG",
            "price": {"value": "0.49", "currency": "USD"},
            "quantity": "5.0",
        }
        messages = [
            {
                "generated_at_utc": "2026-06-14T16:00:30+00:00",
                "subscriptionType": "SUBSCRIPTION_TYPE_ORDER",
                "orderSubscriptionUpdate": {
                    "execution": {
                        "id": "exec-fill",
                        "order": base_order,
                        "lastShares": "2.5",
                        "lastPx": {"value": "0.49", "currency": "USD"},
                        "type": "EXECUTION_TYPE_PARTIAL_FILL",
                        "tradeId": "trade-1",
                    },
                },
            },
            {
                "generated_at_utc": "2026-06-14T16:01:00+00:00",
                "subscriptionType": "SUBSCRIPTION_TYPE_ORDER",
                "orderSubscriptionUpdate": {
                    "execution": {
                        "id": "exec-cancel",
                        "order": {**base_order, "clientOrderId": "life-2"},
                        "type": "EXECUTION_TYPE_CANCELED",
                    },
                },
            },
            {
                "generated_at_utc": "2026-06-14T16:01:30+00:00",
                "subscriptionType": "SUBSCRIPTION_TYPE_ORDER",
                "orderSubscriptionUpdate": {
                    "execution": {
                        "id": "exec-reject",
                        "order": {**base_order, "clientOrderId": "life-3"},
                        "type": "EXECUTION_TYPE_REJECTED",
                        "text": "post-only cross",
                    },
                },
            },
            {
                "generated_at_utc": "2026-06-14T16:02:00+00:00",
                "subscriptionType": "SUBSCRIPTION_TYPE_ORDER",
                "orderSubscriptionUpdate": {
                    "execution": {
                        "id": "exec-replace",
                        "order": {**base_order, "clientOrderId": "life-4"},
                        "type": "EXECUTION_TYPE_REPLACE",
                    },
                },
            },
        ]

        events, fills = lifecycle_events_from_user_events(messages, now)

        self.assertEqual([row["transition"] for row in events], ["filled", "canceled", "rejected", "replaced"])
        self.assertEqual(events[0]["lifecycle_key"], "life-1")
        self.assertEqual(events[0]["source"], "polymarket_us_private_ws")
        self.assertEqual(events[0]["exchange_execution_type"], "EXECUTION_TYPE_PARTIAL_FILL")
        self.assertEqual(events[0]["trade_id"], "trade-1")
        self.assertEqual(events[0]["side"], "YES_BID")
        self.assertAlmostEqual(events[0]["fill_price"], 0.49)
        self.assertAlmostEqual(events[0]["fill_size"], 2.5)
        self.assertEqual(events[1]["lifecycle_key"], "life-2")
        self.assertEqual(events[2]["reason"], "post-only cross")
        self.assertEqual(events[3]["lifecycle_key"], "life-4")
        self.assertEqual(len(fills), 1)
        self.assertEqual(fills[0]["simulator"], "polymarket_us_private_ws")
        self.assertEqual(fills[0]["notes"], "EXECUTION_TYPE_PARTIAL_FILL")

    def test_live_execution_blocks_without_explicit_enablement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_folder = write_run_folder(root)

            payload = build_exchange_reconciliation(
                run_folder,
                execution_mode="live",
                allow_live=False,
                now=NOW,
                env={
                    "POLYMARKET_US_KEY_ID": "key-id",
                    "POLYMARKET_US_SECRET_KEY_STORAGE_REF": "vault://pm/us",
                },
            )

        self.assertEqual(payload["status"], "BLOCK")
        self.assertFalse(payload["trading_verbs_enabled"])
        self.assertIn("live execution requires --allow-live", payload["blockers"])
        self.assertIn("no concrete trading adapter configured", payload["blockers"])

    def test_live_execution_blocks_when_item45_gates_are_not_passing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_folder = write_run_folder(root, preflight_status="BLOCK")

            payload = build_exchange_reconciliation(
                run_folder,
                execution_mode="live",
                allow_live=True,
                now=NOW,
                env={
                    "POLYMARKET_US_KEY_ID": "key-id",
                    "POLYMARKET_US_SECRET_KEY_STORAGE_REF": "vault://pm/us",
                },
            )

        self.assertEqual(payload["status"], "BLOCK")
        self.assertFalse(payload["item45_gates"]["ok"])
        self.assertIn("item-45 gates are not all passing", payload["blockers"])

    def test_live_execution_blocks_a_non_production_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_folder = write_run_folder(
                root,
                release_production_capable=False,
            )

            payload = build_exchange_reconciliation(
                run_folder,
                execution_mode="live",
                allow_live=True,
                now=NOW,
                env={
                    "POLYMARKET_US_KEY_ID": "key-id",
                    "POLYMARKET_US_SECRET_KEY_STORAGE_REF": "vault://pm/us",
                },
            )

        self.assertEqual(payload["status"], "BLOCK")
        self.assertFalse(payload["item45_gates"]["ok"])
        self.assertFalse(
            payload["item45_gates"]["checks"]["release_production_capable"]
        )
        self.assertEqual(
            payload["item45_gates"]["missing"],
            ["release_production_capable"],
        )
        self.assertIn("item-45 gates are not all passing", payload["blockers"])

    def test_credential_diagnostics_redacts_values_and_flags_direct_secret_env(self):
        payload = credential_diagnostics(
            "polymarket_us",
            env={
                "POLYMARKET_US_KEY_ID": "visible-id",
                "POLYMARKET_US_SECRET_KEY_STORAGE_REF": "vault://pm/us",
                "POLYMARKET_US_SECRET_KEY": "do-not-log",
            },
        )
        text = json.dumps(payload, sort_keys=True)

        self.assertFalse(payload["ok"])
        self.assertTrue(payload["values_redacted"])
        self.assertIn("POLYMARKET_US_SECRET_KEY", payload["forbidden_direct_secret_env_names_present"])
        self.assertNotIn("visible-id", text)
        self.assertNotIn("do-not-log", text)
        self.assertNotIn("vault://pm/us", text)

    def test_global_credential_diagnostics_requires_references_not_secret_values(self):
        references = {
            "POLYMARKET_API_KEY_STORAGE_REF": "vault://pm/global/api-key",
            "POLYMARKET_API_SECRET_STORAGE_REF": "vault://pm/global/api-secret",
            "POLYMARKET_API_PASSPHRASE_STORAGE_REF": "vault://pm/global/passphrase",
            "POLYMARKET_FUNDER_ADDRESS": "0x0000000000000000000000000000000000000001",
            "POLYMARKET_PRIVATE_KEY_STORAGE_REF": "vault://pm/global/private-key",
        }
        referenced = credential_diagnostics("polymarket_global", env=references)
        direct = credential_diagnostics(
            "polymarket_global",
            env={
                **references,
                "POLYMARKET_API_KEY": "do-not-log-key",
                "POLYMARKET_API_SECRET": "do-not-log-secret",
                "POLYMARKET_API_PASSPHRASE": "do-not-log-passphrase",
                "POLYMARKET_PRIVATE_KEY": "do-not-log-private-key",
            },
        )
        serialized = json.dumps({"referenced": referenced, "direct": direct}, sort_keys=True)

        self.assertTrue(referenced["ok"])
        self.assertFalse(direct["ok"])
        self.assertEqual(
            set(direct["forbidden_direct_secret_env_names_present"]),
            {
                "POLYMARKET_API_KEY",
                "POLYMARKET_API_SECRET",
                "POLYMARKET_API_PASSPHRASE",
                "POLYMARKET_PRIVATE_KEY",
            },
        )
        self.assertNotIn("vault://", serialized)
        self.assertNotIn("do-not-log", serialized)

    def test_polymarket_us_request_plan_uses_signed_header_shape_without_secret_values(self):
        leg = {
            "lifecycle_key": "life-1",
            "event_slug": "weather-market",
            "side": "YES_BID",
            "price": 0.49,
            "size": 5.0,
        }
        plan = build_adapter_request_plan(
            "polymarket_us",
            "create_post_only",
            leg=leg,
            signer=lambda message: b"fake-ed25519-signature",
            timestamp_ms="1781452800000",
        )
        text = json.dumps(plan, sort_keys=True)

        self.assertTrue(plan["ready"])
        self.assertEqual(plan["method"], "POST")
        self.assertEqual(plan["path"], "/v1/orders")
        self.assertEqual(plan["signature_payload"], "1781452800000POST/v1/orders")
        self.assertEqual(plan["headers"]["X-PM-Signature"], "<signed-redacted>")
        self.assertTrue(plan["body"]["participateDontInitiate"])
        self.assertEqual(plan["body"]["intent"], "ORDER_INTENT_BUY_LONG")
        self.assertNotIn("fake-ed25519-signature", text)

    def test_global_request_plan_requires_presigned_eip712_order_and_l2_signer(self):
        leg = {
            "lifecycle_key": "life-1",
            "clob_token_id": "token-80",
            "side": "YES_ASK",
            "price": 0.51,
            "size": 5.0,
        }

        blocked = build_adapter_request_plan(
            "polymarket_global",
            "create_post_only",
            leg=leg,
            timestamp_ms="1781452800000",
        )
        ready = build_adapter_request_plan(
            "polymarket_global",
            "create_post_only",
            leg=leg,
            metadata={
                "signed_order": {
                    "tokenId": "token-80",
                    "side": "SELL",
                    "signature": "0xsigned",
                },
                "owner": "owner-id",
            },
            signer=lambda message: b"fake-hmac-signature",
            timestamp_ms="1781452800000",
        )
        text = json.dumps(ready, sort_keys=True)

        self.assertFalse(blocked["ready"])
        self.assertIn("pre-signed EIP-712 order", "; ".join(blocked["blockers"]))
        self.assertIn("missing injected global CLOB L2 header signer", blocked["blockers"])
        self.assertTrue(ready["ready"])
        self.assertEqual(ready["method"], "POST")
        self.assertEqual(ready["path"], "/order")
        self.assertTrue(ready["body"]["postOnly"])
        self.assertEqual(ready["headers"]["POLY_SIGNATURE"], "<signed-redacted>")
        self.assertNotIn("fake-hmac-signature", text)

    def test_polymarket_us_http_adapter_sends_signed_post_only_request_via_transport(self):
        transport = RecordingTransport(responses=[{"id": "order-1"}])
        adapter = PolymarketUSHTTPAdapter(
            key_id="key-id",
            signer=lambda message: b"fake-us-signature",
            transport=transport,
            base_url="https://api.polymarket.us",
        )
        response = adapter.place_order({
            "lifecycle_key": "life-1",
            "event_slug": "weather-market",
            "side": "YES_BID",
            "price": 0.49,
            "size": 5.0,
        })
        request = transport.requests[0]

        self.assertEqual(response["id"], "order-1")
        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["url"], "https://api.polymarket.us/v1/orders")
        self.assertEqual(request["headers"]["X-PM-Access-Key"], "key-id")
        self.assertEqual(request["headers"]["X-PM-Signature"], "ZmFrZS11cy1zaWduYXR1cmU=")
        self.assertTrue(request["json_body"]["participateDontInitiate"])

    def test_polymarket_us_latency_stopgap_order_reject_is_not_rate_limit_backoff(self):
        transport = RecordingTransport(responses=[{
            "status": 429,
            "message": "Global Rate Limit Exceeded",
        }])
        adapter = PolymarketUSHTTPAdapter(
            key_id="key-id",
            signer=lambda message: b"fake-us-signature",
            transport=transport,
            base_url="https://api.polymarket.us",
        )

        response = adapter.place_order({
            "lifecycle_key": "life-1",
            "event_slug": "weather-market",
            "side": "YES_BID",
            "price": 0.49,
            "size": 5.0,
        })

        self.assertFalse(response["success"])
        self.assertEqual(response["status"], "rejected")
        self.assertEqual(response["reject_class"], "latency_stopgap")
        self.assertEqual(response["order_acceptance"], "not_accepted")
        self.assertFalse(response["rate_limit_backoff_required"])
        self.assertTrue(response["must_refresh_book_before_retry"])
        self.assertIn("refresh book", response["retry_guidance"])

    def test_polymarket_us_latency_stopgap_on_cancel_is_live_readiness_blocker(self):
        transport = RecordingTransport(responses=[{
            "status": 429,
            "message": "Global Rate Limit Exceeded",
        }])
        adapter = PolymarketUSHTTPAdapter(
            key_id="key-id",
            signer=lambda message: b"fake-us-signature",
            transport=transport,
            base_url="https://api.polymarket.us",
        )

        response = adapter.cancel_all()

        self.assertFalse(response["success"])
        self.assertEqual(response["status"], "unexpected_cancel_reject")
        self.assertEqual(response["reject_class"], "unexpected_latency_stopgap_on_cancel")
        self.assertTrue(response["live_readiness_blocker"])
        self.assertIn("verify open orders", response["retry_guidance"])

    def test_polymarket_us_latency_stopgap_http_exception_is_classified(self):
        class FakeResponse:
            status_code = 429

            def json(self):
                return {"message": "Global Rate Limit Exceeded"}

        class FakeHTTPError(Exception):
            response = FakeResponse()

        class RaisingTransport:
            def request(self, *_args, **_kwargs):
                raise FakeHTTPError("429 Global Rate Limit Exceeded")

        adapter = PolymarketUSHTTPAdapter(
            key_id="key-id",
            signer=lambda message: b"fake-us-signature",
            transport=RaisingTransport(),
            base_url="https://api.polymarket.us",
        )

        response = adapter.place_order({
            "lifecycle_key": "life-1",
            "event_slug": "weather-market",
            "side": "YES_BID",
            "price": 0.49,
            "size": 5.0,
        })

        self.assertEqual(response["http_status"], 429)
        self.assertEqual(response["reject_class"], "latency_stopgap")
        self.assertTrue(response["must_refresh_book_before_retry"])

    def test_polymarket_global_http_adapter_requires_presigned_order_for_live_submit(self):
        transport = RecordingTransport(responses=[{"status": "ok"}, {"success": True, "orderID": "0x1"}])
        adapter = PolymarketGlobalHTTPAdapter(
            api_key="api-key",
            address="0xabc",
            passphrase="passphrase",
            signer=lambda message: b"fake-global-signature",
            transport=transport,
            base_url="https://clob.polymarket.com",
        )

        heartbeat = adapter.heartbeat()
        with self.assertRaisesRegex(RuntimeError, "pre-signed EIP-712"):
            adapter.place_order({
                "clob_token_id": "token-80",
                "side": "YES_BID",
                "price": 0.49,
                "size": 5.0,
            })
        posted = adapter.place_order({
            "signed_order": {
                "tokenId": "token-80",
                "side": "BUY",
                "signature": "0xsigned",
            },
            "owner": "owner-id",
        })
        heartbeat_request = transport.requests[0]
        post_request = transport.requests[1]

        self.assertEqual(heartbeat["status"], "ok")
        self.assertTrue(posted["success"])
        self.assertEqual(heartbeat_request["url"], "https://clob.polymarket.com/v1/heartbeats")
        self.assertEqual(post_request["method"], "POST")
        self.assertEqual(post_request["url"], "https://clob.polymarket.com/order")
        self.assertEqual(post_request["headers"]["POLY_SIGNATURE"], "ZmFrZS1nbG9iYWwtc2lnbmF0dXJl")
        self.assertTrue(post_request["json_body"]["postOnly"])


if __name__ == "__main__":
    unittest.main()
