import csv
import json
import os
import sys
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


NOW = "2026-06-14T16:00:00+00:00"


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


def write_csv(path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_run_folder(root, preflight_status="PASS"):
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
    def test_fixture_reconciliation_appends_lifecycle_fills_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_folder = write_run_folder(root)
            fixture = write_json(root / "exchange_fixture.json", {
                "open_orders": [{
                    "lifecycle_key": "life-1",
                    "order_id": "ex-1",
                    "status": "live",
                    "remaining_size": 3.0,
                }],
                "user_events": [{
                    "event_type": "fill",
                    "generated_at_utc": "2026-06-14T16:00:30+00:00",
                    "lifecycle_key": "life-1",
                    "order_id": "ex-1",
                    "run_id": "exchange-run",
                    "market_id": "atlanta",
                    "event_slug": "highest-temperature-in-atlanta-on-june-14-2026",
                    "range_label": "80-81 F",
                    "clob_token_id": "token-80",
                    "side": "YES_BID",
                    "fill_price": 0.49,
                    "fill_size": 2.0,
                    "markout_30m": 0.02,
                }],
                "balances": {"starting_cash_usdc": 25.0, "cash": 25.98},
                "allowances": {"pUSD": 25.0},
                "positions": [{"token_id": "token-80", "size": 2.0}],
                "rewards": {"maker_rebate_usdc": 0.01},
                "fees": {"paid_usdc": 0.02},
                "redemption_status": {
                    "redeemed": True,
                    "redemption_usdc": 1.0,
                    "settlement_pnl_usdc": 0.99,
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
        note_codes = {row["code"] for row in request_diagnostics["live_readiness_notes"]}
        self.assertIn("create_post_only", capability["supported_actions"])
        self.assertEqual(capability["maker_only_order_field"], "participateDontInitiate")
        self.assertTrue(capability["requires_private_user_stream_for_final_order_state"])
        self.assertTrue(capability["requires_cancel_all_zero_open_orders_verification"])
        self.assertTrue(capability["batched_order_results_require_stream_confirmation"])
        self.assertTrue(capability["latency_stopgap_rejects_order_submit"])
        self.assertTrue(capability["latency_stopgap_cancel_exempt"])
        self.assertIn("private_user_stream_required", note_codes)
        self.assertIn("cancel_all_requires_zero_open_orders_confirmation", note_codes)
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
            0.98,
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
        self.assertEqual(heartbeat_request["url"], "https://clob.polymarket.com/heartbeats")
        self.assertEqual(post_request["method"], "POST")
        self.assertEqual(post_request["url"], "https://clob.polymarket.com/order")
        self.assertEqual(post_request["headers"]["POLY_SIGNATURE"], "ZmFrZS1nbG9iYWwtc2lnbmF0dXJl")
        self.assertTrue(post_request["json_body"]["postOnly"])


if __name__ == "__main__":
    unittest.main()
