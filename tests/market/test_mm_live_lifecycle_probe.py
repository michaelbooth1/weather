import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from weather.market.mm_live_lifecycle_probe import (
    CONFIRMATION,
    build_stage1_lifecycle_bundle,
    execute_stage1_lifecycle_probe as _execute_stage1_lifecycle_probe,
)


CONDITION_ID = "0x" + "b" * 64
SUBMIT_DEADLINE = "2099-01-01T00:00:00+00:00"


def execute_stage1_lifecycle_probe(*args, **kwargs):
    kwargs.setdefault("submit_deadline_utc", SUBMIT_DEADLINE)
    kwargs.setdefault(
        "expected_candidate_intent",
        {
            "side": "BUY",
            "price": 0.01,
            "size": 5.0,
            "notional_pusd": 0.05,
            "post_only": True,
        },
    )
    kwargs.setdefault("expected_candidate_tick_size", 0.01)
    kwargs.setdefault("expected_candidate_order_min_size", 5.0)
    return _execute_stage1_lifecycle_probe(*args, **kwargs)


def bootstrap_gate():
    return {
        "required": True,
        "ok": True,
        "schema_version": "mm_platform_bootstrap_v0.3",
        "status": "PASS",
        "platform": "polymarket_global",
        "settlement_unit": "pUSD",
        "condition_id": CONDITION_ID,
        "token_id": "12345",
        "funder_address": "0x" + "a" * 40,
        "sdk_version": "0.6.0",
        "pilot_wallet_max_funding_usdc": 100.0,
        "requested_budget_usdc": 100.0,
        "account_snapshot_sha256": "b" * 64,
        "checks": {"all_bootstrap_checks": True},
        "missing": [],
    }


class FakeClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class FakeAdapter:
    supports_trading = True
    token_id = "12345"
    condition_id = CONDITION_ID
    maker_address = "0x" + "a" * 40
    sdk_version = "0.6.0"

    def __init__(self, clock, dead_man=False, user_event_delay_seconds=0, order_id="order-1"):
        self.clock = clock
        self.dead_man = dead_man
        self.user_event_delay_seconds = user_event_delay_seconds
        self.orders = []
        self.events = []
        self.placed_at = None
        self.last_heartbeat_at = None
        self.heartbeat_calls = 0
        self.place_calls = 0
        self.cancel_all_calls = 0
        self.position_rows = []
        self.capability = None
        self.submit_deadline_utc = None
        self.order_id = order_id

    def authorize_stage1_lifecycle(self, gate, *, submit_deadline_utc):
        self.capability = object()
        self.submit_deadline_utc = submit_deadline_utc
        return self.capability

    def diagnostics(self):
        return {
            "submit_deadline_utc": self.submit_deadline_utc,
            "network_submit_boundary_utc": "2026-08-22T00:00:00+00:00",
            "network_submit_deadline_passed": True,
        }

    def heartbeat(self):
        self.heartbeat_calls += 1
        self.last_heartbeat_at = self.clock()
        return {"status": "ok"}

    def refresh_market_rules(self):
        return {
            "token_id": self.token_id,
            "tick_size": "0.01",
            "min_order_size": "5",
            "best_bid": "0.49",
            "best_ask": "0.51",
            "neg_risk": False,
        }

    def place_order(self, intent, *, stage1_capability=None):
        if stage1_capability is not self.capability:
            raise RuntimeError("missing test Stage 1 capability")
        self.place_calls += 1
        self.placed_at = self.clock()
        self.orders = [{"orderID": self.order_id, "status": "live"}]
        return {"success": True, "orderID": self.order_id, "status": "live"}

    def _apply_dead_man(self):
        if (
            self.dead_man
            and self.orders
            and self.last_heartbeat_at is not None
            and self.clock() - self.last_heartbeat_at >= 15
        ):
            self.orders = []
            self.events.append({
                "id": self.order_id,
                "event_type": "order",
                "type": "CANCELLATION",
                "status": "CANCELED",
            })

    def open_orders(self):
        self._apply_dead_man()
        return list(self.orders)

    def user_events(self):
        self._apply_dead_man()
        if (
            self.orders
            and not any(row.get("orderID") == self.order_id for row in self.events)
            and self.clock() - self.placed_at >= self.user_event_delay_seconds
        ):
            self.events.append({"orderID": self.order_id, "event_type": "order"})
        return list(self.events)

    def positions(self):
        return list(self.position_rows)

    def position_evidence(self, positions=None):
        return {
            "status": "OBSERVED",
            "query_scope": "exact_maker_condition",
            "maker_address": self.maker_address,
            "condition_id": self.condition_id,
            "rows": list(positions or []),
            "response_sha256": "c" * 64,
            "request_url": (
                "https://data-api.polymarket.com/positions?"
                "user=0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa&market="
                f"{CONDITION_ID}"
                "&sizeThreshold=0&limit=500&offset=0"
            ),
            "http_status": 200,
        }

    def cancel_all(self):
        self.cancel_all_calls += 1
        if self.orders:
            self.events.append({
                "id": self.order_id,
                "event_type": "order",
                "type": "CANCELLATION",
                "status": "CANCELED",
            })
        self.orders = []
        return {"canceled": True}


def test_stage1_cancel_all_probe_is_minimum_non_crossing_and_reconciled(tmp_path):
    clock = FakeClock()
    adapter = FakeAdapter(clock)

    result = execute_stage1_lifecycle_probe(
        adapter,
        bootstrap_gate(),
        confirmation=CONFIRMATION,
        cancellation_mode="cancel_all",
        journal_path=tmp_path / "cancel-all.jsonl",
        monotonic_clock=clock,
        sleeper=clock.sleep,
    )

    assert result["status"] == "PASS"
    assert result["intent"] == {
        "token_id": "12345",
        "price": 0.01,
        "size": 5.0,
        "side": "BUY",
    }
    assert result["order_notional_usdc"] == 0.05
    assert result["terminal_user_event_observed"]
    assert result["zero_positions_verified"]
    assert len(result["journal_sha256"]) == 64
    journal_rows = [
        json.loads(line)
        for line in (tmp_path / "cancel-all.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["event_type"] for row in journal_rows][-2:] == [
        "cancellation_verified",
        "probe_passed",
    ]
    assert any(row["event_type"] == "submit_started" for row in journal_rows)
    assert all("secret" not in json.dumps(row).lower() or row.get("secret_values_redacted") for row in journal_rows)
    assert adapter.cancel_all_calls == 1


def test_stage1_dead_man_probe_observes_exchange_cancel_without_refreshing_heartbeat(tmp_path):
    clock = FakeClock()
    adapter = FakeAdapter(clock, dead_man=True)

    result = execute_stage1_lifecycle_probe(
        adapter,
        bootstrap_gate(),
        confirmation=CONFIRMATION,
        cancellation_mode="dead_man",
        journal_path=tmp_path / "dead-man.jsonl",
        monotonic_clock=clock,
        sleeper=clock.sleep,
        poll_interval_seconds=1,
    )

    assert result["status"] == "PASS"
    assert result["cancellation_mode"] == "dead_man"
    assert result["cancellation_observed"]
    assert result["zero_open_orders_verified"]
    assert result["zero_positions_verified"]
    assert adapter.cancel_all_calls == 0
    assert result["cancellation_elapsed_seconds"] >= 10


def test_stage1_submit_boundary_refuses_expired_deadline_before_order(tmp_path):
    clock = FakeClock()
    adapter = FakeAdapter(clock)

    with pytest.raises(RuntimeError, match="submit deadline has expired"):
        execute_stage1_lifecycle_probe(
            adapter,
            bootstrap_gate(),
            confirmation=CONFIRMATION,
            cancellation_mode="cancel_all",
            journal_path=tmp_path / "expired-submit.jsonl",
            submit_deadline_utc="2026-08-22T00:00:00+00:00",
            utc_clock=lambda: datetime(2026, 8, 22, 0, 0, tzinfo=timezone.utc),
            monotonic_clock=clock,
            sleeper=clock.sleep,
        )

    assert adapter.place_calls == 0
    assert adapter.cancel_all_calls == 1


def test_stage1_refuses_when_fresh_rules_differ_from_sealed_candidate_intent(
    tmp_path,
):
    clock = FakeClock()
    adapter = FakeAdapter(clock)

    with pytest.raises(RuntimeError, match="sealed candidate intent"):
        execute_stage1_lifecycle_probe(
            adapter,
            bootstrap_gate(),
            confirmation=CONFIRMATION,
            cancellation_mode="cancel_all",
            journal_path=tmp_path / "candidate-drift.jsonl",
            monotonic_clock=clock,
            sleeper=clock.sleep,
            expected_candidate_intent={
                "side": "BUY",
                "price": 0.02,
                "size": 5.0,
                "notional_pusd": 0.1,
                "post_only": True,
            },
        )

    assert adapter.place_calls == 0
    assert adapter.cancel_all_calls == 1


def test_stage1_cancel_all_keeps_dead_man_alive_until_explicit_cancel(tmp_path):
    clock = FakeClock()
    adapter = FakeAdapter(clock, dead_man=True, user_event_delay_seconds=12)

    result = execute_stage1_lifecycle_probe(
        adapter,
        bootstrap_gate(),
        confirmation=CONFIRMATION,
        cancellation_mode="cancel_all",
        journal_path=tmp_path / "cancel-all-slow-observation.jsonl",
        monotonic_clock=clock,
        sleeper=clock.sleep,
        observation_timeout_seconds=14,
        poll_interval_seconds=1,
    )

    assert result["status"] == "PASS"
    assert result["cancellation_elapsed_seconds"] == 0
    assert adapter.heartbeat_calls >= 3
    assert adapter.cancel_all_calls == 1


def test_stage1_failure_is_journaled_and_cancelled_without_raw_exception_text(tmp_path):
    class MissingUserEventAdapter(FakeAdapter):
        def user_events(self):
            return []

    clock = FakeClock()
    adapter = MissingUserEventAdapter(clock)
    journal_path = tmp_path / "failed.jsonl"

    with pytest.raises(RuntimeError, match="authoritative user stream"):
        execute_stage1_lifecycle_probe(
            adapter,
            bootstrap_gate(),
            confirmation=CONFIRMATION,
            cancellation_mode="cancel_all",
            journal_path=journal_path,
            monotonic_clock=clock,
            sleeper=clock.sleep,
            observation_timeout_seconds=1,
        )

    rows = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]
    failure = rows[-1]
    assert failure["event_type"] == "probe_failed"
    assert failure["phase"] == "authoritative_order_observation"
    assert failure["exception_type"] == "RuntimeError"
    assert "authoritative user stream" not in json.dumps(failure)
    assert failure["cleanup_succeeded"] is True
    assert adapter.cancel_all_calls == 1


def test_stage1_keyboard_interrupt_after_submit_is_journaled_and_cancelled(tmp_path):
    class InterruptedPlacementAdapter(FakeAdapter):
        def place_order(self, intent, *, stage1_capability=None):
            super().place_order(intent, stage1_capability=stage1_capability)
            raise KeyboardInterrupt("RAW-INTERRUPT-TEXT")

    clock = FakeClock()
    adapter = InterruptedPlacementAdapter(clock)
    journal_path = tmp_path / "interrupted-after-submit.jsonl"

    with pytest.raises(KeyboardInterrupt, match="RAW-INTERRUPT-TEXT"):
        execute_stage1_lifecycle_probe(
            adapter,
            bootstrap_gate(),
            confirmation=CONFIRMATION,
            cancellation_mode="cancel_all",
            journal_path=journal_path,
            monotonic_clock=clock,
            sleeper=clock.sleep,
        )

    rows = [
        json.loads(line)
        for line in journal_path.read_text(encoding="utf-8").splitlines()
    ]
    failure = rows[-1]
    assert failure["event_type"] == "probe_failed"
    assert failure["phase"] == "placement"
    assert failure["exception_type"] == "KeyboardInterrupt"
    assert failure["cleanup_succeeded"] is True
    assert "RAW-INTERRUPT-TEXT" not in json.dumps(failure)
    assert adapter.place_calls == 1
    assert adapter.cancel_all_calls == 1
    assert adapter.orders == []


def test_stage1_blocks_existing_position_before_mutation(tmp_path):
    clock = FakeClock()
    adapter = FakeAdapter(clock)
    adapter.position_rows = [{"asset_id": adapter.token_id, "size": "1"}]

    with pytest.raises(RuntimeError, match="zero positions at start"):
        execute_stage1_lifecycle_probe(
            adapter,
            bootstrap_gate(),
            confirmation=CONFIRMATION,
            cancellation_mode="cancel_all",
            journal_path=tmp_path / "stage1-existing-position.jsonl",
            monotonic_clock=clock,
            sleeper=clock.sleep,
        )

    assert adapter.place_calls == 0


def test_stage1_probe_rejects_missing_confirmation_before_mutation(tmp_path):
    clock = FakeClock()
    adapter = FakeAdapter(clock)

    with pytest.raises(RuntimeError, match="exact confirmation token"):
        execute_stage1_lifecycle_probe(
            adapter,
            bootstrap_gate(),
            confirmation="wrong",
            cancellation_mode="cancel_all",
            journal_path=tmp_path / "must-not-exist.jsonl",
            monotonic_clock=clock,
            sleeper=clock.sleep,
        )

    assert adapter.place_calls == 0
    assert not (tmp_path / "must-not-exist.jsonl").exists()


def test_stage1_probe_revalidates_operator_budget_cap_before_mutation(tmp_path):
    clock = FakeClock()
    adapter = FakeAdapter(clock)
    gate = bootstrap_gate()
    gate["requested_budget_usdc"] = 100.01

    with pytest.raises(RuntimeError, match="requested_budget"):
        execute_stage1_lifecycle_probe(
            adapter,
            gate,
            confirmation=CONFIRMATION,
            cancellation_mode="cancel_all",
            journal_path=tmp_path / "oversized-budget.jsonl",
            monotonic_clock=clock,
            sleeper=clock.sleep,
        )

    assert adapter.place_calls == 0
    assert not (tmp_path / "oversized-budget.jsonl").exists()


def test_stage1_binds_adapter_wallet_condition_token_and_sdk_before_journal(tmp_path):
    clock = FakeClock()
    adapter = FakeAdapter(clock)
    adapter.maker_address = "0x" + "d" * 40
    journal_path = tmp_path / "binding-mismatch.jsonl"

    with pytest.raises(RuntimeError, match="adapter/bootstrap binding failed: maker"):
        execute_stage1_lifecycle_probe(
            adapter,
            bootstrap_gate(),
            confirmation=CONFIRMATION,
            cancellation_mode="cancel_all",
            journal_path=journal_path,
            monotonic_clock=clock,
            sleeper=clock.sleep,
        )

    assert adapter.place_calls == 0
    assert not journal_path.exists()


def test_stage1_rejects_position_reads_without_exact_response_evidence(tmp_path):
    class UnscopedPositionAdapter(FakeAdapter):
        def position_evidence(self, positions=None):
            return {"status": "NOT_CONFIGURED", "rows": list(positions or [])}

    clock = FakeClock()
    adapter = UnscopedPositionAdapter(clock)

    with pytest.raises(RuntimeError, match="exact-scope response evidence"):
        execute_stage1_lifecycle_probe(
            adapter,
            bootstrap_gate(),
            confirmation=CONFIRMATION,
            cancellation_mode="cancel_all",
            journal_path=tmp_path / "unscoped-position.jsonl",
            monotonic_clock=clock,
            sleeper=clock.sleep,
        )

    assert adapter.place_calls == 0


def test_stage1_rejects_any_trade_lifecycle_before_claiming_no_fill(tmp_path):
    class MatchedAdapter(FakeAdapter):
        def user_events(self):
            rows = super().user_events()
            if self.orders and not any(row.get("official_event_type") == "trade" for row in rows):
                self.events.append({
                    "order_id": self.order_id,
                    "event_type": "trade_pending",
                    "official_event_type": "trade",
                    "official_trade_status": "MATCHED",
                })
            return list(self.events)

    clock = FakeClock()
    adapter = MatchedAdapter(clock)

    with pytest.raises(RuntimeError, match="unexpected trade lifecycle"):
        execute_stage1_lifecycle_probe(
            adapter,
            bootstrap_gate(),
            confirmation=CONFIRMATION,
            cancellation_mode="cancel_all",
            journal_path=tmp_path / "matched.jsonl",
            monotonic_clock=clock,
            sleeper=clock.sleep,
        )

    assert adapter.cancel_all_calls == 1


def test_stage1_bundle_verifies_distinct_journals_and_derives_no_fill_evidence(tmp_path):
    gate = bootstrap_gate()
    cancel_clock = FakeClock()
    cancel_result = execute_stage1_lifecycle_probe(
        FakeAdapter(cancel_clock, order_id="cancel-order"),
        gate,
        confirmation=CONFIRMATION,
        cancellation_mode="cancel_all",
        journal_path=tmp_path / "cancel-all.jsonl",
        monotonic_clock=cancel_clock,
        sleeper=cancel_clock.sleep,
    )
    dead_clock = FakeClock()
    dead_result = execute_stage1_lifecycle_probe(
        FakeAdapter(dead_clock, dead_man=True, order_id="dead-man-order"),
        gate,
        confirmation=CONFIRMATION,
        cancellation_mode="dead_man",
        journal_path=tmp_path / "dead-man.jsonl",
        monotonic_clock=dead_clock,
        sleeper=dead_clock.sleep,
        poll_interval_seconds=1,
    )

    bundle = build_stage1_lifecycle_bundle(gate, cancel_result, dead_result)

    assert bundle["schema_version"] == "mm_stage1_lifecycle_bundle_v0.2"
    assert bundle["status"] == "PASS"
    assert bundle["derived_platform_evidence"] == {
        "starting_open_orders_rest_verified": True,
        "order_update_verified": True,
        "fill_event_verified": False,
        "no_fill_lifecycle_verified": True,
        "final_state_reconciliation_verified": True,
        "cancel_all_request_verified": True,
        "cancel_all_zero_open_orders_verified": True,
        "dead_man_automatic_cancel_verified": True,
        "heartbeat_acknowledgment_verified": True,
    }
    assert len(bundle["bundle_sha256"]) == 64

    oversized_result = dict(cancel_result)
    oversized_result["order_notional_usdc"] = 10.01
    with pytest.raises(RuntimeError, match="notional"):
        build_stage1_lifecycle_bundle(gate, oversized_result, dead_result)


def test_stage1_bundle_rejects_journal_tampering(tmp_path):
    gate = bootstrap_gate()
    cancel_clock = FakeClock()
    cancel_result = execute_stage1_lifecycle_probe(
        FakeAdapter(cancel_clock, order_id="cancel-order"),
        gate,
        confirmation=CONFIRMATION,
        cancellation_mode="cancel_all",
        journal_path=tmp_path / "cancel-all.jsonl",
        monotonic_clock=cancel_clock,
        sleeper=cancel_clock.sleep,
    )
    dead_clock = FakeClock()
    dead_result = execute_stage1_lifecycle_probe(
        FakeAdapter(dead_clock, dead_man=True, order_id="dead-man-order"),
        gate,
        confirmation=CONFIRMATION,
        cancellation_mode="dead_man",
        journal_path=tmp_path / "dead-man.jsonl",
        monotonic_clock=dead_clock,
        sleeper=dead_clock.sleep,
        poll_interval_seconds=1,
    )
    with (tmp_path / "dead-man.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{}\n")

    with pytest.raises(RuntimeError, match="journal hash does not match"):
        build_stage1_lifecycle_bundle(gate, cancel_result, dead_result)


@pytest.mark.parametrize("tamper", ["missing", "duplicate", "reordered"])
def test_stage1_bundle_requires_deadline_before_submit_event_sequence(
    tmp_path, tamper
):
    gate = bootstrap_gate()
    cancel_clock = FakeClock()
    cancel_result = execute_stage1_lifecycle_probe(
        FakeAdapter(cancel_clock, order_id="cancel-order"),
        gate,
        confirmation=CONFIRMATION,
        cancellation_mode="cancel_all",
        journal_path=tmp_path / "cancel-all.jsonl",
        monotonic_clock=cancel_clock,
        sleeper=cancel_clock.sleep,
    )
    dead_clock = FakeClock()
    dead_result = execute_stage1_lifecycle_probe(
        FakeAdapter(dead_clock, dead_man=True, order_id="dead-man-order"),
        gate,
        confirmation=CONFIRMATION,
        cancellation_mode="dead_man",
        journal_path=tmp_path / "dead-man.jsonl",
        monotonic_clock=dead_clock,
        sleeper=dead_clock.sleep,
        poll_interval_seconds=1,
    )
    path = Path(cancel_result["journal_path"])
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    deadline_index = next(
        index
        for index, row in enumerate(rows)
        if row["event_type"] == "submit_deadline_verified"
    )
    if tamper == "missing":
        rows.pop(deadline_index)
    elif tamper == "duplicate":
        rows.insert(deadline_index, dict(rows[deadline_index]))
    else:
        intent_index = next(
            index
            for index, row in enumerate(rows)
            if row["event_type"] == "intent_prepared"
        )
        rows[intent_index], rows[deadline_index] = rows[deadline_index], rows[intent_index]
    raw = ("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n").encode()
    path.write_bytes(raw)
    cancel_result["journal_sha256"] = hashlib.sha256(raw).hexdigest()

    with pytest.raises(RuntimeError, match="does not bind|missing required"):
        build_stage1_lifecycle_bundle(gate, cancel_result, dead_result)
