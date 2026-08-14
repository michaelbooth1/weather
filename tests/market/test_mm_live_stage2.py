import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import urlencode

import pytest

from weather.market.mm_geoblock import collect_official_geoblock_evidence
from weather.market.mm_live_stage2 import (
    CONFIRMATION,
    build_stage2_session_envelope,
    execute_stage2_maker_session,
)
from weather.market.mm_official_adapter import OfficialPolymarketGlobalAdapter


MAKER = "0x" + "a" * 40
CONDITION = "0x" + "b" * 64
TOKEN = "123456789"
NOW = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
HASH = "c" * 64


def eligible_geoblock():
    class Response:
        status = 200

        def read(self, _limit):
            return json.dumps({
                "blocked": False,
                "country": "CH",
                "region": "ZH",
                "ip": "203.0.113.9",
            }).encode("utf-8")

        def close(self):
            pass

    return collect_official_geoblock_evidence(
        opener=lambda _request, timeout: Response(),
        proxy_detector=lambda: {},
    )


def platform_gate():
    return {
        "required": True,
        "ok": True,
        "schema_version": "mm_platform_verification_v0.4",
        "platform": "polymarket_global",
        "settlement_unit": "pUSD",
        "target_date": "2026-08-14",
        "artifact_sha256": HASH,
        "condition_id": CONDITION,
        "token_id": TOKEN,
        "funder_address": MAKER,
        "requested_budget_usdc": 25.0,
        "pilot_wallet_max_funding_usdc": 100.0,
        "stage1_lifecycle_bundle_sha256": "d" * 64,
        "signature_type_id": 3,
        "geoblock_country": "CH",
        "geoblock_region": "ZH",
        "sdk_contract": {
            "distribution": "py-clob-client-v2",
            "version": "1.1.0",
            "exact_version_verified": True,
        },
        "dead_man_heartbeat": {
            "endpoint": "/v1/heartbeats",
            "acknowledgment_verified": True,
            "rotating_id_chain_verified": True,
            "automatic_cancel_verified": True,
        },
        "checks": {"complete_v0_4": True},
        "missing": [],
    }


def quote_decision(*, generated=NOW):
    return {
        "generated_at_utc": generated.isoformat(),
        "target_date": "2026-08-14",
        "run_mode": "live-pilot",
        "shadow_mode": False,
        "run_budget_usdc": 25.0,
        "budget_action": "reserved",
        "quote_ttl_seconds": 1.0,
        "quote_permission": True,
        "live_trade_permission": True,
        "action": "QUOTE",
        "market_id": "zurich",
        "event_slug": "highest-temperature-in-zurich-on-august-14-2026",
        "condition_id": CONDITION,
        "clob_token_id": TOKEN,
        "range_label": "80-81 F",
        "snapshot_id": "snapshot-1",
        "model_version": "pooled-v1",
        "served_model_version": "pooled-v1",
        "model_variant_id": "served-current",
        "model_variant_artifact_hash": "e" * 64,
        "policy_version": "mm-policy-v1",
        "policy_hash": "f" * 64,
        "fair_probability": 0.50,
        "bid_price": 0.50,
        "bid_size": 5.0,
        "ask_price": 0.52,
        "ask_size": 5.0,
        "quote_risk_usdc": 2.5,
        "event_notional": 0.0,
        "band_notional": 0.0,
        "daily_loss_pusd": 0.0,
        "source_fresh": True,
        "heartbeat_ok": True,
        "current_high_trusted": True,
        "latency_budget_status": "ok",
    }


def market_preflight():
    gate_names = (
        "active_event",
        "snapshot_model_rows",
        "model_freshness",
        "source_status_rows",
        "source_status_fresh",
        "source_status_degradation",
        "clob_discovery",
        "clob_tokens",
        "clob_books",
        "clob_features",
        "clob_freshness",
        "observation_trigger",
        "promotion_state",
        "reward_metadata",
        "data_layer_live_gate",
        "platform_verification_gate",
        "exchange_economics_gate",
    )
    return {
        "status": "PASS",
        "market_id": "zurich",
        "target_date": "2026-08-14",
        "gates": [{"name": name, "ok": True} for name in gate_names],
        "live_gate": {
            "required": True,
            "pilot_flag": True,
            "confirm_live_orders": True,
            "live_ready": True,
            "platform_verified": True,
            "release_production_capable": True,
            "ok": True,
        },
    }


def paper_counterfactual(*, generated=NOW):
    row = quote_decision(generated=generated)
    row.update({
        "run_id": "paper-run-1",
        "run_mode": "paper-live-forward",
        "shadow_mode": True,
        "live_trade_permission": False,
    })
    payload = {
        "schema_version": "mm_live_stage2_paper_counterfactual_v0.1",
        "artifact_recorded_at_utc": generated.isoformat(),
        "quote_row": row,
    }
    return json.dumps(payload, sort_keys=True).encode("utf-8")


def paper_with_quote_updates(**updates):
    payload = json.loads(paper_counterfactual().decode("utf-8"))
    payload["quote_row"].update(updates)
    return json.dumps(payload, sort_keys=True).encode("utf-8")


def public_capture_evidence(*, observed=NOW):
    payload = {
        "probe_receipt": {
            "schema_version": "execution_tape_bounded_probe_v0.2",
            "ok": True,
            "stage": "proved",
            "repo_head": "2" * 40,
            "required_ancestor": "3" * 40,
            "connected_seed_set_proved": True,
            "new_trade_observations": 1,
            "baseline_integrity_counters": {
                "parse_rejections": 0,
                "unrouted_trades": 0,
                "ambiguous_routes": 0,
            },
            "final_integrity_counters": {
                "parse_rejections": 0,
                "unrouted_trades": 0,
                "ambiguous_routes": 0,
            },
            "capture_workers_before": 3,
            "capture_workers_after": 3,
            "snapshot_heartbeat_before": (
                observed - timedelta(seconds=60)
            ).isoformat(),
            "snapshot_heartbeat_after": (
                observed - timedelta(seconds=30)
            ).isoformat(),
            "finished_at": (observed - timedelta(seconds=20)).isoformat(),
        },
        "live_status": {
            "schema_version": "execution_tape_status_v0.1",
            "updated_at_utc": observed.isoformat(),
            "state": "CONNECTED",
            "last_seed_error": None,
            "coordinator_session_id": "capture-session-1",
            "active_market_day_count": 1,
            "active_market_days": [{
                "market_id": "zurich",
                "target_date": "2026-08-14",
                "event_slug": "highest-temperature-in-zurich-on-august-14-2026",
                "connection_state": "CONNECTED",
                "evidence_interpretation": "TRADES_CONTINUOUSLY_CONNECTED",
            }],
        },
        "market_day_status": {
            "schema_version": "execution_tape_status_v0.1",
            "updated_at_utc": observed.isoformat(),
            "market_id": "zurich",
            "target_date": "2026-08-14",
            "event_slug": "highest-temperature-in-zurich-on-august-14-2026",
            "connection_state": "CONNECTED",
            "evidence_interpretation": "TRADES_CONTINUOUSLY_CONNECTED",
            "session_id": "capture-websocket-session-1",
            "seed_sha256": "4" * 64,
        },
    }
    return {
        "probe_receipt_bytes": json.dumps(
            payload["probe_receipt"],
            sort_keys=True,
        ).encode("utf-8"),
        "live_status_bytes": json.dumps(
            payload["live_status"],
            sort_keys=True,
        ).encode("utf-8"),
        "market_day_status_bytes": json.dumps(
            payload["market_day_status"],
            sort_keys=True,
        ).encode("utf-8"),
    }


def position_evidence(rows):
    query = urlencode({
        "user": MAKER,
        "market": CONDITION,
        "sizeThreshold": 0,
        "limit": 500,
        "offset": 0,
    })
    return {
        "status": "OBSERVED",
        "query_scope": "exact_maker_condition",
        "maker_address": MAKER,
        "condition_id": CONDITION,
        "request_url": f"https://data-api.polymarket.com/positions?{query}",
        "http_status": 200,
        "response_sha256": HASH,
        "rows": list(rows),
    }


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.value += float(seconds)


class FakeAdapter:
    supports_trading = True
    token_id = TOKEN
    condition_id = CONDITION
    maker_address = MAKER
    max_order_notional = Decimal("10")

    def __init__(self, mode="no_fill"):
        self.mode = mode
        self.open = []
        self.event_rows = []
        self.position_rows = []
        self.capability = object()
        self.submit_calls = 0
        self.cancel_calls = 0
        self.cancel_order_calls = 0
        self.heartbeat_calls = 0
        self.user_event_calls = 0
        self.fail_open_orders_once = False

    def authorize_stage2_maker_session(self, gate, envelope):
        assert gate["ok"] is True
        assert envelope["max_network_submits"] == 1
        return self.capability

    def heartbeat(self):
        self.heartbeat_calls += 1
        return {"heartbeat_id": f"hb-{self.heartbeat_calls}"}

    def refresh_market_rules(self):
        return {
            "token_id": TOKEN,
            "condition_id": CONDITION,
            "min_order_size": "5",
            "tick_size": "0.01",
            "neg_risk": False,
            "best_bid": "0.49",
            "best_ask": "0.51",
        }

    def place_order(self, intent, *, stage2_capability=None):
        assert stage2_capability is self.capability
        assert intent["side"] == "BUY"
        self.submit_calls += 1
        self.open = [{"orderID": "order-1"}]
        self.event_rows = [{
            "event_type": "order",
            "official_event_type": "order",
            "order_id": "order-1",
            "raw_event_sha256": (
                "short" if self.mode == "invalid_event" else "1" * 64
            ),
        }]
        if self.mode == "taker":
            self.event_rows.append({
                "event_type": "trade",
                "official_event_type": "trade",
                "order_id": "order-1",
                "trade_id": "trade-taker",
                "liquidity_role": "TAKER",
                "fill_size": "5",
                "fill_price": "0.50",
                "raw_event_sha256": "2" * 64,
            })
        return {
            "success": True,
            "orderID": "order-1",
            "status": "live",
            "tradeIDs": [],
            "transactionsHashes": [],
        }

    def open_orders(self):
        if self.fail_open_orders_once:
            self.fail_open_orders_once = False
            raise RuntimeError("sensitive open-order reader detail")
        return list(self.open)

    def user_events(self):
        self.user_event_calls += 1
        if (
            self.mode in {"fill", "mismatch", "collateral_mismatch"}
            and self.user_event_calls >= 2
            and self.open
        ):
            self.open = []
            self.position_rows = [{
                "proxyWallet": MAKER,
                "conditionId": CONDITION,
                "asset": TOKEN,
                "size": "4" if self.mode == "mismatch" else "5",
            }]
            self.event_rows.append({
                "event_type": "trade",
                "official_event_type": "trade",
                "order_id": "order-1",
                "trade_id": "trade-maker",
                "transaction_hash": "0xabc",
                "liquidity_role": "MAKER",
                "fill_size": "5",
                "fill_price": "0.50",
                "fee_rate_bps": "0",
                "raw_event_sha256": "3" * 64,
            })
        return list(self.event_rows)

    def positions(self):
        return list(self.position_rows)

    def position_evidence(self, positions):
        return position_evidence(positions)

    def refresh_collateral_evidence(self):
        owned = sum(Decimal(str(row["size"])) for row in self.position_rows)
        spent = Decimal("0") if self.mode == "collateral_mismatch" else owned * Decimal("0.50")
        balance_atomic = int((Decimal("100") - spent) * Decimal("1000000"))
        return {
            "status": "OBSERVED",
            "query_scope": "authenticated_collateral_balance_allowance",
            "balance_atomic": str(balance_atomic),
            "allowances_atomic": {"exchange": "100000000"},
            "response_sha256": HASH,
        }

    def cancel_order(self, order_id):
        assert order_id == "order-1"
        self.cancel_order_calls += 1
        self.open = []
        self.event_rows.append({
            "event_type": "canceled",
            "official_event_type": "order",
            "order_id": "order-1",
            "raw_event_sha256": "4" * 64,
        })
        return {"canceled": order_id}

    def cancel_all(self):
        self.cancel_calls += 1
        self.open = []
        return {"canceled": True}

    def fees(self):
        return {"token_id": TOKEN, "fee_rate_bps": 0}

    def rewards(self):
        return {
            "current_markets": [],
            "maker_rebate_evidence": {
                "status": "NOT_CONFIGURED",
                "payout_cycle_complete": False,
                "rows": [],
            },
        }


@pytest.mark.parametrize("mode,expected_fill_count", [("no_fill", 0), ("fill", 1)])
def test_stage2_executes_one_buy_and_reconciles_authoritative_state(
    tmp_path,
    mode,
    expected_fill_count,
):
    adapter = FakeAdapter(mode)
    clock = Clock()
    result = execute_stage2_maker_session(
        adapter,
        platform_gate(),
        quote_decision(),
        market_preflight(),
        paper_counterfactual(),
        public_capture_evidence(),
        confirmation=CONFIRMATION,
        session_budget_pusd=25,
        journal_path=tmp_path / f"{mode}.jsonl",
        monotonic_clock=clock,
        wall_clock=lambda: NOW,
        sleeper=clock.sleep,
        heartbeat_interval_seconds=0.5,
        poll_interval_seconds=0.25,
    )

    assert result["status"] == "PASS"
    assert result["platform"] == "polymarket_global"
    assert result["order"]["side"] == "BUY"
    assert result["order"]["post_only_forced"] is True
    assert result["order"]["network_submit_count"] == 1
    assert len(result["confirmed_maker_fills"]) == expected_fill_count
    assert result["final_reconciliation"]["zero_open_orders_verified"] is True
    assert result["final_reconciliation"]["expected_collateral_spend_pusd"] == (
        "0" if mode == "no_fill" else "2.50"
    )
    assert result["rebate"]["accepted_paid_rebate_pusd"] == "0"
    assert result["fees"]["accepted_actual_fee_pusd"] == "0"
    assert result["fees"]["actual_maker_fee_observed"] is True
    assert result["economic_acceptance"]["complete"] is False
    assert result["economic_acceptance"]["unpaid_or_unverified_rebate_credited"] is False
    assert adapter.submit_calls == 1
    assert adapter.cancel_calls == 1
    assert len(result["journal_sha256"]) == 64


def test_stage2_blocks_stale_quote_before_authorization_or_mutation(tmp_path):
    adapter = FakeAdapter()
    stale = quote_decision(generated=NOW - timedelta(seconds=2))

    with pytest.raises(RuntimeError, match="fresh"):
        execute_stage2_maker_session(
            adapter,
            platform_gate(),
            stale,
            market_preflight(),
            paper_counterfactual(),
            public_capture_evidence(),
            confirmation=CONFIRMATION,
            session_budget_pusd=25,
            journal_path=tmp_path / "stale.jsonl",
            wall_clock=lambda: NOW,
        )

    assert adapter.submit_calls == 0
    assert adapter.cancel_calls == 0
    assert not (tmp_path / "stale.jsonl").exists()


def test_stage2_taker_lifecycle_fails_and_still_cancels_all(tmp_path):
    adapter = FakeAdapter("taker")
    clock = Clock()

    with pytest.raises(RuntimeError, match="taker lifecycle"):
        execute_stage2_maker_session(
            adapter,
            platform_gate(),
            quote_decision(),
            market_preflight(),
            paper_counterfactual(),
            public_capture_evidence(),
            confirmation=CONFIRMATION,
            session_budget_pusd=25,
            journal_path=tmp_path / "taker.jsonl",
            monotonic_clock=clock,
            wall_clock=lambda: NOW,
            sleeper=clock.sleep,
            poll_interval_seconds=0.25,
        )

    assert adapter.submit_calls == 1
    assert adapter.cancel_calls == 1
    journal = (tmp_path / "taker.jsonl").read_text(encoding="utf-8")
    assert "session_failed" in journal
    assert "RuntimeError" in journal


def test_stage2_malformed_user_event_fails_and_still_cancels_all(tmp_path):
    adapter = FakeAdapter("invalid_event")
    clock = Clock()

    with pytest.raises(RuntimeError, match="malformed or unbound"):
        execute_stage2_maker_session(
            adapter,
            platform_gate(),
            quote_decision(),
            market_preflight(),
            paper_counterfactual(),
            public_capture_evidence(),
            confirmation=CONFIRMATION,
            session_budget_pusd=25,
            journal_path=tmp_path / "invalid-event.jsonl",
            monotonic_clock=clock,
            wall_clock=lambda: NOW,
            sleeper=clock.sleep,
            poll_interval_seconds=0.25,
        )

    assert adapter.cancel_order_calls == 1
    assert adapter.cancel_calls == 1


def test_stage2_final_position_mismatch_is_journaled_after_safe_cleanup(tmp_path):
    adapter = FakeAdapter("mismatch")
    clock = Clock()

    with pytest.raises(RuntimeError, match="confirmed fills do not equal"):
        execute_stage2_maker_session(
            adapter,
            platform_gate(),
            quote_decision(),
            market_preflight(),
            paper_counterfactual(),
            public_capture_evidence(),
            confirmation=CONFIRMATION,
            session_budget_pusd=25,
            journal_path=tmp_path / "mismatch.jsonl",
            monotonic_clock=clock,
            wall_clock=lambda: NOW,
            sleeper=clock.sleep,
            poll_interval_seconds=0.25,
        )

    assert adapter.cancel_calls == 1
    journal = (tmp_path / "mismatch.jsonl").read_text(encoding="utf-8")
    assert '"phase":"final_reconciliation"' in journal
    assert "confirmed fills do not equal" not in journal


def test_stage2_final_collateral_mismatch_is_journaled_after_cleanup(tmp_path):
    adapter = FakeAdapter("collateral_mismatch")
    clock = Clock()

    with pytest.raises(RuntimeError, match="collateral change does not equal"):
        execute_stage2_maker_session(
            adapter,
            platform_gate(),
            quote_decision(),
            market_preflight(),
            paper_counterfactual(),
            public_capture_evidence(),
            confirmation=CONFIRMATION,
            session_budget_pusd=25,
            journal_path=tmp_path / "collateral-mismatch.jsonl",
            monotonic_clock=clock,
            wall_clock=lambda: NOW,
            sleeper=clock.sleep,
            poll_interval_seconds=0.25,
        )

    assert adapter.cancel_calls == 1
    journal = (tmp_path / "collateral-mismatch.jsonl").read_text(encoding="utf-8")
    assert '"phase":"final_reconciliation"' in journal
    assert "collateral change does not equal" not in journal


def test_stage2_requires_complete_named_live_preflight(tmp_path):
    adapter = FakeAdapter()
    incomplete = market_preflight()
    incomplete["gates"] = incomplete["gates"][:-1]

    with pytest.raises(RuntimeError, match="required_preflight_gates"):
        execute_stage2_maker_session(
            adapter,
            platform_gate(),
            quote_decision(),
            incomplete,
            paper_counterfactual(),
            public_capture_evidence(),
            confirmation=CONFIRMATION,
            session_budget_pusd=25,
            journal_path=tmp_path / "incomplete.jsonl",
            wall_clock=lambda: NOW,
        )

    assert adapter.submit_calls == 0
    assert not (tmp_path / "incomplete.jsonl").exists()


def test_stage2_requires_exact_frozen_paper_counterfactual(tmp_path):
    adapter = FakeAdapter()
    paper = paper_with_quote_updates(bid_price=0.49)

    with pytest.raises(RuntimeError, match="exact_treatment_numbers"):
        execute_stage2_maker_session(
            adapter,
            platform_gate(),
            quote_decision(),
            market_preflight(),
            paper,
            public_capture_evidence(),
            confirmation=CONFIRMATION,
            session_budget_pusd=25,
            journal_path=tmp_path / "paper-mismatch.jsonl",
            wall_clock=lambda: NOW,
        )

    assert adapter.submit_calls == 0
    assert not (tmp_path / "paper-mismatch.jsonl").exists()


def test_stage2_rejects_reconstructed_evidence_dictionaries(tmp_path):
    adapter = FakeAdapter()
    capture = public_capture_evidence()
    capture["probe_receipt_bytes"] = json.loads(
        capture["probe_receipt_bytes"].decode("utf-8")
    )

    with pytest.raises(RuntimeError, match="retained JSON artifact bytes"):
        execute_stage2_maker_session(
            adapter,
            platform_gate(),
            quote_decision(),
            market_preflight(),
            json.loads(paper_counterfactual().decode("utf-8")),
            public_capture_evidence(),
            confirmation=CONFIRMATION,
            session_budget_pusd=25,
            journal_path=tmp_path / "reconstructed-paper.jsonl",
            wall_clock=lambda: NOW,
        )

    with pytest.raises(RuntimeError, match="retained JSON artifact bytes"):
        execute_stage2_maker_session(
            adapter,
            platform_gate(),
            quote_decision(),
            market_preflight(),
            paper_counterfactual(),
            capture,
            confirmation=CONFIRMATION,
            session_budget_pusd=25,
            journal_path=tmp_path / "reconstructed-capture.jsonl",
            wall_clock=lambda: NOW,
        )

    assert adapter.submit_calls == 0
    assert not (tmp_path / "reconstructed-paper.jsonl").exists()
    assert not (tmp_path / "reconstructed-capture.jsonl").exists()


def test_stage2_rejects_under_reserved_buy_risk_before_authorization(tmp_path):
    adapter = FakeAdapter()
    quote = quote_decision()
    quote["quote_risk_usdc"] = 2.49
    paper = paper_with_quote_updates(quote_risk_usdc=2.49)

    with pytest.raises(RuntimeError, match="quote_risk"):
        execute_stage2_maker_session(
            adapter,
            platform_gate(),
            quote,
            market_preflight(),
            paper,
            public_capture_evidence(),
            confirmation=CONFIRMATION,
            session_budget_pusd=25,
            journal_path=tmp_path / "under-reserved.jsonl",
            wall_clock=lambda: NOW,
        )

    assert adapter.submit_calls == 0
    assert not (tmp_path / "under-reserved.jsonl").exists()


def test_stage2_requires_fresh_exact_scope_public_capture(tmp_path):
    adapter = FakeAdapter()
    stale_capture = public_capture_evidence(
        observed=NOW - timedelta(seconds=11),
    )

    with pytest.raises(RuntimeError, match="status_current"):
        execute_stage2_maker_session(
            adapter,
            platform_gate(),
            quote_decision(),
            market_preflight(),
            paper_counterfactual(),
            stale_capture,
            confirmation=CONFIRMATION,
            session_budget_pusd=25,
            journal_path=tmp_path / "stale-capture.jsonl",
            wall_clock=lambda: NOW,
        )

    assert adapter.submit_calls == 0
    assert not (tmp_path / "stale-capture.jsonl").exists()


def test_stage2_enforces_cumulative_daily_loss_before_submit(tmp_path):
    adapter = FakeAdapter()
    quote = quote_decision()
    quote["daily_loss_pusd"] = 24
    paper = paper_with_quote_updates(daily_loss_pusd=24)

    with pytest.raises(RuntimeError, match="frozen risk ceiling"):
        execute_stage2_maker_session(
            adapter,
            platform_gate(),
            quote,
            market_preflight(),
            paper,
            public_capture_evidence(),
            confirmation=CONFIRMATION,
            session_budget_pusd=25,
            journal_path=tmp_path / "daily-loss.jsonl",
            wall_clock=lambda: NOW,
        )

    assert adapter.submit_calls == 0
    assert adapter.cancel_calls == 1


def test_stage2_cancel_all_survives_pre_cancel_open_reader_failure(tmp_path):
    adapter = FakeAdapter()
    clock = Clock()

    def sleeper(seconds):
        clock.sleep(seconds)
        if clock.value >= 1:
            adapter.fail_open_orders_once = True

    with pytest.raises(RuntimeError, match="cleanup or final evidence"):
        execute_stage2_maker_session(
            adapter,
            platform_gate(),
            quote_decision(),
            market_preflight(),
            paper_counterfactual(),
            public_capture_evidence(),
            confirmation=CONFIRMATION,
            session_budget_pusd=25,
            journal_path=tmp_path / "open-reader-failure.jsonl",
            monotonic_clock=clock,
            wall_clock=lambda: NOW,
            sleeper=sleeper,
            heartbeat_interval_seconds=0.5,
            poll_interval_seconds=0.25,
        )

    assert adapter.cancel_order_calls == 1
    assert adapter.cancel_calls == 1
    journal = (tmp_path / "open-reader-failure.jsonl").read_text(encoding="utf-8")
    assert "sensitive open-order reader detail" not in journal
    assert "RuntimeError" in journal


def test_official_adapter_stage2_capability_is_buy_only_and_single_submit():
    class OrderType:
        GTC = "GTC"

    class Client:
        def __init__(self):
            self.posts = 0
            self.heartbeats = 0

        def get_open_orders(self):
            return []

        def get_address(self):
            return "0x" + "e" * 40

        def get_closed_only_mode(self):
            return {"closed_only": False}

        def get_order_book(self, token_id):
            return {
                "asset_id": token_id,
                "market": CONDITION,
                "min_order_size": "5",
                "tick_size": "0.01",
                "neg_risk": False,
                "bids": [{"price": "0.49"}],
                "asks": [{"price": "0.51"}],
            }

        def get_tick_size(self, token_id):
            return "0.01"

        def post_heartbeat(self, heartbeat_id):
            self.heartbeats += 1
            return {"heartbeat_id": f"hb-{self.heartbeats}"}

        def create_order(self, order, *, options):
            return {
                "signer": MAKER,
                "maker": MAKER,
                "tokenId": order["token_id"],
                "signatureType": 3,
                "signature": "0x" + "f" * 130,
            }

        def post_order(self, signed_order, *, order_type, post_only):
            self.posts += 1
            return {
                "success": True,
                "orderID": "official-order",
                "status": "live",
                "tradeIDs": [],
                "transactionsHashes": [],
            }

        def cancel_all(self):
            return {"canceled": True}

    client = Client()
    adapter = OfficialPolymarketGlobalAdapter(
        client,
        token_id=TOKEN,
        user_event_reader=lambda: [],
        user_event_health_reader=lambda: {"state": "SUBSCRIPTION_PROVEN"},
        position_reader=lambda: position_evidence([]),
        maker_address=MAKER,
        condition_id=CONDITION,
        order_args_factory=lambda **kwargs: kwargs,
        order_payload_factory=lambda **kwargs: kwargs,
        order_type_factory=OrderType,
        order_options_factory=lambda **kwargs: kwargs,
        sdk_version="1.1.0",
        authoritative_readers_verified=True,
        utc_clock=lambda: NOW,
        geoblock_checker=eligible_geoblock,
    )
    envelope = build_stage2_session_envelope(
        adapter,
        platform_gate(),
        quote_decision(),
        market_preflight(),
        paper_counterfactual(),
        public_capture_evidence(),
        session_budget_pusd=25,
        now=NOW,
    )
    capability = adapter.authorize_stage2_maker_session(platform_gate(), envelope)
    adapter.heartbeat()
    adapter.refresh_market_rules()
    response = adapter.place_order(
        {"token_id": TOKEN, "price": "0.50", "size": "5", "side": "BUY"},
        stage2_capability=capability,
    )

    assert response["status"] == "live"
    assert client.posts == 1
    assert adapter.diagnostics()["stage2_capability_consumed"] is True
    with pytest.raises(RuntimeError, match="authorized capability"):
        adapter.place_order(
            {"token_id": TOKEN, "price": "0.50", "size": "5", "side": "BUY"},
            stage2_capability=capability,
        )
    assert client.posts == 1

    sell_client = Client()
    owned_rows = [{
        "proxyWallet": MAKER,
        "conditionId": CONDITION,
        "asset": TOKEN,
        "size": "5",
    }]
    sell_adapter = OfficialPolymarketGlobalAdapter(
        sell_client,
        token_id=TOKEN,
        user_event_reader=lambda: [],
        user_event_health_reader=lambda: {"state": "SUBSCRIPTION_PROVEN"},
        position_reader=lambda: position_evidence(owned_rows),
        maker_address=MAKER,
        condition_id=CONDITION,
        order_args_factory=lambda **kwargs: kwargs,
        order_payload_factory=lambda **kwargs: kwargs,
        order_type_factory=OrderType,
        order_options_factory=lambda **kwargs: kwargs,
        sdk_version="1.1.0",
        authoritative_readers_verified=True,
        utc_clock=lambda: NOW,
        geoblock_checker=eligible_geoblock,
    )
    sell_envelope = build_stage2_session_envelope(
        sell_adapter,
        platform_gate(),
        quote_decision(),
        market_preflight(),
        paper_counterfactual(),
        public_capture_evidence(),
        session_budget_pusd=25,
        now=NOW,
    )
    sell_capability = sell_adapter.authorize_stage2_maker_session(
        platform_gate(),
        sell_envelope,
    )
    sell_adapter.heartbeat()
    sell_adapter.refresh_market_rules()
    with pytest.raises(RuntimeError, match="backed BUY orders only"):
        sell_adapter.place_order(
            {
                "token_id": TOKEN,
                "price": "0.50",
                "size": "5",
                "side": "SELL",
                "owned_inventory_verified": True,
            },
            stage2_capability=sell_capability,
        )
    assert sell_client.posts == 0

    tight_client = Client()
    tight_adapter = OfficialPolymarketGlobalAdapter(
        tight_client,
        token_id=TOKEN,
        user_event_reader=lambda: [],
        user_event_health_reader=lambda: {"state": "SUBSCRIPTION_PROVEN"},
        position_reader=lambda: position_evidence([]),
        maker_address=MAKER,
        condition_id=CONDITION,
        order_args_factory=lambda **kwargs: kwargs,
        order_payload_factory=lambda **kwargs: kwargs,
        order_type_factory=OrderType,
        order_options_factory=lambda **kwargs: kwargs,
        sdk_version="1.1.0",
        authoritative_readers_verified=True,
        utc_clock=lambda: NOW,
        geoblock_checker=eligible_geoblock,
    )
    tight_quote = quote_decision()
    tight_quote["daily_loss_pusd"] = 24
    tight_paper = paper_with_quote_updates(daily_loss_pusd=24)
    tight_envelope = build_stage2_session_envelope(
        tight_adapter,
        platform_gate(),
        tight_quote,
        market_preflight(),
        tight_paper,
        public_capture_evidence(),
        session_budget_pusd=25,
        now=NOW,
    )
    tight_capability = tight_adapter.authorize_stage2_maker_session(
        platform_gate(),
        tight_envelope,
    )
    tight_adapter.heartbeat()
    tight_adapter.refresh_market_rules()
    with pytest.raises(RuntimeError, match="frozen Stage 2 cap"):
        tight_adapter.place_order(
            {"token_id": TOKEN, "price": "0.50", "size": "5", "side": "BUY"},
            stage2_capability=tight_capability,
        )
    assert tight_client.posts == 0

    expiry_clock = [NOW]
    expiry_client = Client()
    expiry_adapter = OfficialPolymarketGlobalAdapter(
        expiry_client,
        token_id=TOKEN,
        user_event_reader=lambda: [],
        user_event_health_reader=lambda: {"state": "SUBSCRIPTION_PROVEN"},
        position_reader=lambda: position_evidence([]),
        maker_address=MAKER,
        condition_id=CONDITION,
        order_args_factory=lambda **kwargs: kwargs,
        order_payload_factory=lambda **kwargs: kwargs,
        order_type_factory=OrderType,
        order_options_factory=lambda **kwargs: kwargs,
        sdk_version="1.1.0",
        authoritative_readers_verified=True,
        utc_clock=lambda: expiry_clock[0],
        geoblock_checker=eligible_geoblock,
    )
    expiry_envelope = build_stage2_session_envelope(
        expiry_adapter,
        platform_gate(),
        quote_decision(),
        market_preflight(),
        paper_counterfactual(),
        public_capture_evidence(),
        session_budget_pusd=25,
        now=NOW,
    )
    expiry_capability = expiry_adapter.authorize_stage2_maker_session(
        platform_gate(),
        expiry_envelope,
    )
    expiry_adapter.heartbeat()
    expiry_adapter.refresh_market_rules()
    expiry_clock[0] = NOW + timedelta(seconds=2)
    with pytest.raises(RuntimeError, match="evidence expired"):
        expiry_adapter.place_order(
            {"token_id": TOKEN, "price": "0.50", "size": "5", "side": "BUY"},
            stage2_capability=expiry_capability,
        )
    assert expiry_client.posts == 0
