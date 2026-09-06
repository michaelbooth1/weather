import json
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from weather.market import mm_geographic_eligibility as geography
from weather.market.mm_live_lifecycle_probe import (
    BOOTSTRAP_SCHEMA_VERSION,
    CONFIRMATION,
    JOURNAL_SCHEMA_VERSION,
    LIFECYCLE_BUNDLE_SCHEMA_VERSION,
    SCHEMA_VERSION,
    build_stage1_lifecycle_bundle,
    execute_stage1_lifecycle_probe as _execute_stage1_lifecycle_probe,
    verify_stage1_user_stream_journal,
)


CONDITION_ID = "0x" + "b" * 64
SUBMIT_DEADLINE = "2099-01-01T00:00:00+00:00"
REPO_ROOT = Path(__file__).resolve().parents[2]


def geographic_eligibility_receipt(checked_at):
    checked = checked_at.astimezone(timezone.utc)
    decision = {"blocked": False, "country": "GB", "region": "ENG"}
    receipt = {
        "agreement": True,
        "blocker_code": None,
        "checked_at_utc": geography._iso_utc(checked),
        "eligible": True,
        "endpoint": geography.GEOBLOCK_ENDPOINT,
        "fresh_until_utc": geography._iso_utc(
            checked + timedelta(seconds=geography.MAX_RECEIPT_AGE_SECONDS)
        ),
        "freshness_max_age_seconds": geography.MAX_RECEIPT_AGE_SECONDS,
        "official": {
            **decision,
            "decision_sha256": geography._canonical_digest(decision),
        },
        "operator_attestation": {
            "confirmation": geography.PHYSICAL_LOCATION_CONFIRMATION,
            "no_circumvention": True,
            "physical_location_eligible": True,
        },
        "privacy": {
            "source_address_retained": False,
            "secret_values_retained": False,
        },
        "receipt_payload_sha256": None,
        "response_binding": {
            "body_bytes": 80,
            "redacted_body_sha256": geography._canonical_digest(decision),
            "content_type": "application/json",
            "final_url": geography.GEOBLOCK_ENDPOINT,
            "http_status": 200,
        },
        "schema_version": geography.RECEIPT_SCHEMA_VERSION,
        "status": "PASS",
    }
    receipt["receipt_payload_sha256"] = geography._payload_digest(receipt)
    return receipt


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
    kwargs.setdefault("expected_candidate_fee_rate", 0.05)
    kwargs.setdefault("expected_candidate_neg_risk", False)
    kwargs.setdefault(
        "pre_submit_attestor",
        lambda: geographic_eligibility_receipt(datetime.now(timezone.utc)),
    )
    return _execute_stage1_lifecycle_probe(*args, **kwargs)


def bootstrap_gate():
    return {
        "required": True,
        "ok": True,
        "schema_version": "mm_platform_bootstrap_v0.6",
        "status": "PASS",
        "platform": "polymarket_global",
        "settlement_unit": "pUSD",
        "condition_id": CONDITION_ID,
        "token_id": "12345",
        "funder_address": "0x" + "a" * 40,
        "sdk_version": "0.6.0",
        "isolated_pilot_wallet": True,
        "pilot_wallet_max_funding_usdc": 100.0,
        "requested_budget_usdc": 10.0,
        "account_snapshot_sha256": "b" * 64,
        "checks": {"all_bootstrap_checks": True},
        "missing": [],
    }


def test_tracked_research_templates_expose_the_active_hardening_contracts():
    bootstrap = json.loads(
        (REPO_ROOT / "docs/research/mm_platform_bootstrap_template.json").read_text(
            encoding="utf-8"
        )
    )
    bundle = json.loads(
        (
            REPO_ROOT / "docs/research/mm_stage1_lifecycle_bundle_template.json"
        ).read_text(encoding="utf-8")
    )
    verification = json.loads(
        (
            REPO_ROOT / "docs/research/mm_platform_verification_template.json"
        ).read_text(encoding="utf-8")
    )

    assert bootstrap["schema_version"] == "mm_platform_bootstrap_v0.6"
    assert {
        "fee_rule_verified",
        "fee_rate_bps",
        "neg_risk",
        "candidate_neg_risk",
    }.issubset(bootstrap["market_snapshot"])
    assert "candidate_fee_rate" not in bootstrap["market_snapshot"]
    assert bundle["schema_version"] == "mm_stage1_lifecycle_bundle_v0.3"
    assert bundle["bootstrap_schema_version"] == "mm_platform_bootstrap_v0.6"
    assert "user_stream_journal_evidence" in bundle
    assert {
        "terminal_order_rest_verified",
        "account_trades_rest_verified",
        "final_user_stream_journals_verified",
        "action_time_collateral_verified",
        "no_fill_collateral_reconciliation_verified",
    }.issubset(bundle["derived_platform_evidence"])
    assert (
        verification["stage1_lifecycle_bundle"]["schema_version"]
        == "mm_stage1_lifecycle_bundle_v0.3"
    )
    assert (
        verification["stage1_lifecycle_bundle"]["bootstrap_schema_version"]
        == "mm_platform_bootstrap_v0.6"
    )
    assert "user_stream_journal_evidence" in verification["stage1_lifecycle_bundle"]
    assert {
        "terminal_order_rest_verified",
        "account_trades_rest_verified",
        "final_user_stream_journals_verified",
        "action_time_collateral_verified",
        "no_fill_collateral_reconciliation_verified",
    }.issubset(
        verification["stage1_lifecycle_bundle"]["derived_platform_evidence"]
    )
    assert {
        "terminal_order_rest_verified",
        "account_trades_rest_verified",
        "final_user_stream_journals_verified",
        "action_time_collateral_verified",
        "no_fill_collateral_reconciliation_verified",
    }.issubset(verification["private_user_stream"])


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
        self.geographic_eligibility_fresh_until_utc = None
        self.network_submit_boundary_utc = None
        self.order_id = order_id
        self.collateral_refresh_calls = 0
        self.collateral_payloads = [
            {
                "balance": "100000000",
                "allowances": {"exchange": "100000000"},
            }
        ]

    def authorize_stage1_lifecycle(self, gate, *, submit_deadline_utc):
        self.capability = object()
        self.submit_deadline_utc = submit_deadline_utc
        return self.capability

    def diagnostics(self):
        return {
            "submit_deadline_utc": self.submit_deadline_utc,
            "network_submit_boundary_utc": self.network_submit_boundary_utc,
            "network_submit_deadline_passed": True,
            "geographic_eligibility_fresh_until_utc": (
                self.geographic_eligibility_fresh_until_utc
            ),
            "network_submit_geography_freshness_passed": True,
            "post_sign_order_placement_boundary_verified": True,
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
            "fee_rate_bps": "500",
        }

    def refresh_balance_allowance(self):
        index = min(self.collateral_refresh_calls, len(self.collateral_payloads) - 1)
        self.collateral_refresh_calls += 1
        payload = self.collateral_payloads[index]
        return {
            "balance": payload["balance"],
            "allowances": dict(payload["allowances"]),
        }

    def place_order(
        self,
        intent,
        *,
        stage1_capability=None,
        geographic_eligibility_fresh_until_utc=None,
    ):
        if stage1_capability is not self.capability:
            raise RuntimeError("missing test Stage 1 capability")
        self.geographic_eligibility_fresh_until_utc = (
            geographic_eligibility_fresh_until_utc
        )
        fresh_until = datetime.fromisoformat(
            str(geographic_eligibility_fresh_until_utc).replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        self.network_submit_boundary_utc = (
            fresh_until - timedelta(seconds=30)
        ).isoformat()
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
                "size_matched": "0",
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
                "size_matched": "0",
            })
        self.orders = []
        return {"canceled": True}

    def get_order(self, order_id):
        return {
            "id": order_id,
            "market": self.condition_id,
            "asset_id": self.token_id,
            "maker_address": self.maker_address,
            "status": "ORDER_STATUS_CANCELED",
            "size_matched": "0",
            "associate_trades": [],
        }

    def account_trades(self):
        return []


def attach_stream_journal(result, path):
    rows = [
        {
            "schema_version": "mm_user_stream_journal_v0.1",
            "recorded_at_utc": "2026-08-22T00:00:00+00:00",
            "event_type": "user_event",
            "payload": {
                "order_id": result["order_id"],
                "event_type": "canceled",
                "official_event_type": "order",
                "official_order_transition": "CANCELLATION",
                "official_order_status": "CANCELED",
                "size_matched": "0",
            },
        },
        {
            "schema_version": "mm_user_stream_journal_v0.1",
            "recorded_at_utc": "2026-08-22T00:00:01+00:00",
            "event_type": "stream_stopped",
        },
    ]
    raw = ("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n").encode()
    path.write_bytes(raw)
    result["user_stream_journal_path"] = str(path.resolve())
    result["user_stream_journal_sha256"] = hashlib.sha256(raw).hexdigest()
    result["cleanup_final_user_stream_journal_sha256"] = hashlib.sha256(
        raw
    ).hexdigest()
    result["user_stream_journal_row_count"] = len(rows)
    result["user_stream_scoped_order_event_count"] = 1
    return result


def test_stage1_final_user_stream_requires_terminal_stop_and_cleanup_hash(tmp_path):
    result = {"order_id": "order-1"}
    path = tmp_path / "final-stream.jsonl"
    attach_stream_journal(result, path)
    assert verify_stage1_user_stream_journal(path, result)[
        "terminal_stream_stopped_verified"
    ] is True

    rows = [json.loads(line) for line in path.read_text().splitlines()]
    missing_stop = tmp_path / "missing-stop.jsonl"
    missing_raw = (
        "\n".join(json.dumps(row, sort_keys=True) for row in rows[:-1]) + "\n"
    ).encode()
    missing_stop.write_bytes(missing_raw)
    missing_result = dict(result)
    missing_result["user_stream_journal_path"] = str(missing_stop.resolve())
    missing_result["user_stream_journal_sha256"] = hashlib.sha256(
        missing_raw
    ).hexdigest()
    missing_result["cleanup_final_user_stream_journal_sha256"] = hashlib.sha256(
        missing_raw
    ).hexdigest()
    with pytest.raises(RuntimeError, match="terminal stream_stopped"):
        verify_stage1_user_stream_journal(missing_stop, missing_result)

    after_stop = tmp_path / "event-after-stop.jsonl"
    after_rows = rows + [
        {
            "schema_version": "mm_user_stream_journal_v0.1",
            "event_type": "subscription_sent",
        }
    ]
    after_raw = (
        "\n".join(json.dumps(row, sort_keys=True) for row in after_rows) + "\n"
    ).encode()
    after_stop.write_bytes(after_raw)
    after_result = dict(result)
    after_result["user_stream_journal_path"] = str(after_stop.resolve())
    after_result["user_stream_journal_sha256"] = hashlib.sha256(after_raw).hexdigest()
    after_result["cleanup_final_user_stream_journal_sha256"] = hashlib.sha256(
        after_raw
    ).hexdigest()
    with pytest.raises(RuntimeError, match="terminal stream_stopped"):
        verify_stage1_user_stream_journal(after_stop, after_result)

    tampered = path.read_text().replace('"event_type": "canceled"', '"event_type": "cancelled"')
    path.write_text(tampered, encoding="utf-8")
    with pytest.raises(RuntimeError, match="hash does not match result"):
        verify_stage1_user_stream_journal(path, result)


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
    assert result["submit_boundary_market_rules_verified"] is True
    assert result["submit_boundary_heartbeat_acknowledged"] is True
    assert result["submit_boundary_geography_before_heartbeat_verified"] is True
    assert result["post_sign_order_placement_boundary_verified"] is True
    assert result["zero_positions_verified"]
    assert result["collateral_no_fill_reconciliation_verified"] is True
    assert result["submit_collateral_snapshot_sha256"] == result[
        "post_cancel_collateral_snapshot_sha256"
    ]
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
    assert adapter.collateral_refresh_calls == 2


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


def test_stage1_submit_adjacent_fee_or_neg_risk_drift_blocks_before_order(tmp_path):
    cases = (
        ("fee-drift-to-zero", {"fee_rate_bps": "0"}, "fee/neg-risk rules differ"),
        ("neg-risk", {"neg_risk": True}, "fee/neg-risk rules differ"),
    )
    for name, drift, error_match in cases:
        clock = FakeClock()
        adapter = FakeAdapter(clock)
        original_refresh = adapter.refresh_market_rules
        refresh_count = 0

        def refresh_with_submit_drift():
            nonlocal refresh_count
            refresh_count += 1
            rules = original_refresh()
            if refresh_count >= 2:
                rules.update(drift)
            return rules

        adapter.refresh_market_rules = refresh_with_submit_drift
        journal_path = tmp_path / f"{name}-submit-drift.jsonl"

        with pytest.raises(RuntimeError, match=error_match):
            execute_stage1_lifecycle_probe(
                adapter,
                bootstrap_gate(),
                confirmation=CONFIRMATION,
                cancellation_mode="cancel_all",
                journal_path=journal_path,
                monotonic_clock=clock,
                sleeper=clock.sleep,
            )

        assert refresh_count == 2
        assert adapter.place_calls == 0
        assert adapter.cancel_all_calls == 1
        events = [
            json.loads(line)["event_type"]
            for line in journal_path.read_text().splitlines()
        ]
        assert "submit_started" not in events


def test_stage1_network_boundary_rule_drift_after_geography_blocks_before_order(
    tmp_path,
):
    clock = FakeClock()
    adapter = FakeAdapter(clock)
    original_refresh = adapter.refresh_market_rules
    refresh_count = 0

    def refresh_with_network_boundary_drift():
        nonlocal refresh_count
        refresh_count += 1
        rules = original_refresh()
        if refresh_count == 3:
            rules["neg_risk"] = True
        return rules

    adapter.refresh_market_rules = refresh_with_network_boundary_drift
    with pytest.raises(RuntimeError, match="fee/neg-risk rules differ"):
        execute_stage1_lifecycle_probe(
            adapter,
            bootstrap_gate(),
            confirmation=CONFIRMATION,
            cancellation_mode="cancel_all",
            journal_path=tmp_path / "network-boundary-drift.jsonl",
            monotonic_clock=clock,
            sleeper=clock.sleep,
        )

    assert refresh_count == 3
    assert adapter.place_calls == 0
    assert adapter.cancel_all_calls == 1


def test_stage1_action_time_collateral_blocks_outside_budget_before_order(tmp_path):
    cases = (
        ("low-balance", "9999999", "10000000"),
        ("over-cap", "100000001", "10000000"),
        ("low-allowance", "100000000", "9999999"),
    )
    for name, balance, allowance in cases:
        clock = FakeClock()
        adapter = FakeAdapter(clock)
        adapter.collateral_payloads = [
            {"balance": balance, "allowances": {"exchange": allowance}}
        ]
        journal_path = tmp_path / f"{name}-collateral.jsonl"

        with pytest.raises(RuntimeError, match="action-time collateral"):
            execute_stage1_lifecycle_probe(
                adapter,
                bootstrap_gate(),
                confirmation=CONFIRMATION,
                cancellation_mode="cancel_all",
                journal_path=journal_path,
                monotonic_clock=clock,
                sleeper=clock.sleep,
            )

        assert adapter.collateral_refresh_calls == 1
        assert adapter.place_calls == 0
        events = [
            json.loads(line)["event_type"]
            for line in journal_path.read_text().splitlines()
        ]
        assert "submit_started" not in events


def test_stage1_revalidates_geography_after_callback_and_blocks_stale_receipt(
    tmp_path,
):
    class WallClock:
        def __init__(self):
            self.value = datetime(2026, 8, 24, 1, 0, tzinfo=timezone.utc)

        def __call__(self):
            return self.value

    clock = FakeClock()
    wall_clock = WallClock()
    adapter = FakeAdapter(clock)
    callback_calls = []
    journal_path = tmp_path / "stale-submit-geography.jsonl"

    def attest():
        callback_calls.append(wall_clock())
        receipt = geographic_eligibility_receipt(wall_clock())
        wall_clock.value += timedelta(
            seconds=geography.MAX_RECEIPT_AGE_SECONDS + 1
        )
        return receipt

    with pytest.raises(geography.GeographicEligibilityError, match="RECEIPT_STALE"):
        execute_stage1_lifecycle_probe(
            adapter,
            bootstrap_gate(),
            confirmation=CONFIRMATION,
            cancellation_mode="cancel_all",
            journal_path=journal_path,
            monotonic_clock=clock,
            sleeper=clock.sleep,
            utc_clock=wall_clock,
            pre_submit_attestor=attest,
        )

    assert len(callback_calls) == 1
    assert adapter.collateral_refresh_calls == 1
    assert adapter.place_calls == 0
    assert adapter.cancel_all_calls == 1
    rows = [json.loads(line) for line in journal_path.read_text().splitlines()]
    assert rows[-1]["event_type"] == "probe_failed"
    assert rows[-1]["phase"] == "submit_adjacent_geography"
    assert all(row["event_type"] != "submit_started" for row in rows)


def test_stage1_revalidates_geography_after_final_rules_before_heartbeat(tmp_path):
    class WallClock:
        def __init__(self):
            self.value = datetime(2026, 8, 24, 1, 0, tzinfo=timezone.utc)

        def __call__(self):
            return self.value

    clock = FakeClock()
    wall_clock = WallClock()
    adapter = FakeAdapter(clock)
    original_refresh = adapter.refresh_market_rules
    refresh_count = 0
    journal_path = tmp_path / "rules-expire-geography.jsonl"

    def slow_final_rules():
        nonlocal refresh_count
        refresh_count += 1
        rules = original_refresh()
        if refresh_count == 3:
            wall_clock.value += timedelta(
                seconds=geography.MAX_RECEIPT_AGE_SECONDS + 1
            )
        return rules

    adapter.refresh_market_rules = slow_final_rules
    with pytest.raises(geography.GeographicEligibilityError, match="RECEIPT_STALE"):
        execute_stage1_lifecycle_probe(
            adapter,
            bootstrap_gate(),
            confirmation=CONFIRMATION,
            cancellation_mode="cancel_all",
            journal_path=journal_path,
            monotonic_clock=clock,
            sleeper=clock.sleep,
            utc_clock=wall_clock,
            pre_submit_attestor=lambda: geographic_eligibility_receipt(
                wall_clock()
            ),
        )

    assert refresh_count == 3
    assert adapter.heartbeat_calls == 1
    assert adapter.place_calls == 0
    rows = [json.loads(line) for line in journal_path.read_text().splitlines()]
    assert rows[-1]["phase"] == "submit_boundary_heartbeat_geography"
    assert all(row["event_type"] != "submit_started" for row in rows)


def test_stage1_rejects_a_network_boundary_before_the_geography_check(tmp_path):
    class PreAttestationBoundaryAdapter(FakeAdapter):
        def diagnostics(self):
            payload = super().diagnostics()
            fresh_until = datetime.fromisoformat(
                str(payload["geographic_eligibility_fresh_until_utc"]).replace(
                    "Z", "+00:00"
                )
            )
            payload["network_submit_boundary_utc"] = (
                fresh_until
                - timedelta(seconds=geography.MAX_RECEIPT_AGE_SECONDS + 1)
            ).isoformat()
            return payload

    clock = FakeClock()
    adapter = PreAttestationBoundaryAdapter(clock)

    with pytest.raises(RuntimeError, match="network submit crossed"):
        execute_stage1_lifecycle_probe(
            adapter,
            bootstrap_gate(),
            confirmation=CONFIRMATION,
            cancellation_mode="cancel_all",
            journal_path=tmp_path / "pre-attestation-boundary.jsonl",
            monotonic_clock=clock,
            sleeper=clock.sleep,
        )

    assert adapter.place_calls == 1
    assert adapter.cancel_all_calls == 1
    assert adapter.orders == []


def test_stage1_no_fill_requires_exact_post_cancel_collateral_reconciliation(tmp_path):
    clock = FakeClock()
    adapter = FakeAdapter(clock)
    adapter.collateral_payloads = [
        {
            "balance": "100000000",
            "allowances": {"exchange": "100000000"},
        },
        {
            "balance": "99999999",
            "allowances": {"exchange": "100000000"},
        },
    ]
    journal_path = tmp_path / "post-cancel-collateral-drift.jsonl"

    with pytest.raises(RuntimeError, match="did not reconcile exactly"):
        execute_stage1_lifecycle_probe(
            adapter,
            bootstrap_gate(),
            confirmation=CONFIRMATION,
            cancellation_mode="cancel_all",
            journal_path=journal_path,
            monotonic_clock=clock,
            sleeper=clock.sleep,
        )

    assert adapter.collateral_refresh_calls == 2
    assert adapter.place_calls == 1
    events = [
        json.loads(line)["event_type"]
        for line in journal_path.read_text().splitlines()
    ]
    assert "submit_started" in events
    assert "probe_passed" not in events


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
        def place_order(
            self,
            intent,
            *,
            stage1_capability=None,
            geographic_eligibility_fresh_until_utc=None,
        ):
            super().place_order(
                intent,
                stage1_capability=stage1_capability,
                geographic_eligibility_fresh_until_utc=(
                    geographic_eligibility_fresh_until_utc
                ),
            )
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


@pytest.mark.parametrize("matched_size", [None, "0.01"])
def test_stage1_rejects_terminal_cancel_without_exact_zero_matched_size(
    tmp_path, matched_size
):
    class UnsafeCancellationAdapter(FakeAdapter):
        def cancel_all(self):
            response = super().cancel_all()
            cancellation = self.events[-1]
            if matched_size is None:
                cancellation.pop("size_matched", None)
            else:
                cancellation["size_matched"] = matched_size
            return response

    clock = FakeClock()
    adapter = UnsafeCancellationAdapter(clock)

    with pytest.raises(RuntimeError, match="matched-size|matched size"):
        execute_stage1_lifecycle_probe(
            adapter,
            bootstrap_gate(),
            confirmation=CONFIRMATION,
            cancellation_mode="cancel_all",
            journal_path=tmp_path / "unsafe-cancel.jsonl",
            monotonic_clock=clock,
            sleeper=clock.sleep,
        )


def test_stage1_rejects_late_match_during_post_cancel_quiescence(tmp_path):
    class LateMatchedAdapter(FakeAdapter):
        def user_events(self):
            rows = super().user_events()
            canceled = any(row.get("type") == "CANCELLATION" for row in rows)
            matched = any(row.get("official_event_type") == "trade" for row in rows)
            if canceled and not matched and self.clock() - self.placed_at >= 0.5:
                self.events.append({
                    "order_id": self.order_id,
                    "event_type": "trade_pending",
                    "official_event_type": "trade",
                    "official_trade_status": "MATCHED",
                })
            return list(self.events)

    clock = FakeClock()
    adapter = LateMatchedAdapter(clock)
    with pytest.raises(RuntimeError, match="unexpected trade lifecycle"):
        execute_stage1_lifecycle_probe(
            adapter,
            bootstrap_gate(),
            confirmation=CONFIRMATION,
            cancellation_mode="cancel_all",
            journal_path=tmp_path / "late-match.jsonl",
            monotonic_clock=clock,
            sleeper=clock.sleep,
            poll_interval_seconds=0.25,
        )


def test_stage1_rejects_nonzero_terminal_rest_match(tmp_path):
    class RestMatchedAdapter(FakeAdapter):
        def get_order(self, order_id):
            row = super().get_order(order_id)
            row["size_matched"] = "0.01"
            row["associate_trades"] = ["trade-1"]
            return row

    clock = FakeClock()
    with pytest.raises(RuntimeError, match="zero-fill cancellation"):
        execute_stage1_lifecycle_probe(
            RestMatchedAdapter(clock),
            bootstrap_gate(),
            confirmation=CONFIRMATION,
            cancellation_mode="cancel_all",
            journal_path=tmp_path / "rest-match.jsonl",
            monotonic_clock=clock,
            sleeper=clock.sleep,
        )


def test_stage1_refuses_the_published_v03_bootstrap_contract(tmp_path):
    gate = bootstrap_gate()
    gate["schema_version"] = "mm_platform_bootstrap_v0.3"

    with pytest.raises(RuntimeError, match="adapter/bootstrap binding failed: schema"):
        execute_stage1_lifecycle_probe(
            FakeAdapter(FakeClock()),
            gate,
            confirmation=CONFIRMATION,
            cancellation_mode="cancel_all",
            journal_path=tmp_path / "legacy-bootstrap.jsonl",
        )

    assert BOOTSTRAP_SCHEMA_VERSION == "mm_platform_bootstrap_v0.6"


@pytest.mark.parametrize("existing_wallet", [False, True])
def test_stage1_bundle_verifies_distinct_journals_and_derives_no_fill_evidence(
    tmp_path, existing_wallet
):
    gate = bootstrap_gate()
    if existing_wallet:
        gate.update(
            pilot_capital_mode="existing_wallet_test_allocation",
            pilot_test_allocation_pusd=100,
            isolated_pilot_wallet=False,
            pilot_wallet_max_funding_usdc=None,
        )

    def test_adapter(clock, **kwargs):
        adapter = FakeAdapter(clock, **kwargs)
        if existing_wallet:
            adapter.collateral_payloads[0]["balance"] = "275480000"
        return adapter

    cancel_clock = FakeClock()
    cancel_result = execute_stage1_lifecycle_probe(
        test_adapter(cancel_clock, order_id="cancel-order"),
        gate,
        confirmation=CONFIRMATION,
        cancellation_mode="cancel_all",
        journal_path=tmp_path / "cancel-all.jsonl",
        monotonic_clock=cancel_clock,
        sleeper=cancel_clock.sleep,
    )
    attach_stream_journal(cancel_result, tmp_path / "cancel-all-stream.jsonl")
    dead_clock = FakeClock()
    dead_result = execute_stage1_lifecycle_probe(
        test_adapter(dead_clock, dead_man=True, order_id="dead-man-order"),
        gate,
        confirmation=CONFIRMATION,
        cancellation_mode="dead_man",
        journal_path=tmp_path / "dead-man.jsonl",
        monotonic_clock=dead_clock,
        sleeper=dead_clock.sleep,
        poll_interval_seconds=1,
    )
    attach_stream_journal(dead_result, tmp_path / "dead-man-stream.jsonl")

    bundle = build_stage1_lifecycle_bundle(gate, cancel_result, dead_result)

    assert bundle["schema_version"] == "mm_stage1_lifecycle_bundle_v0.3"
    assert bundle["status"] == "PASS"
    assert bundle["derived_platform_evidence"] == {
        "starting_open_orders_rest_verified": True,
        "order_update_verified": True,
        "fill_event_verified": False,
        "no_fill_lifecycle_verified": True,
        "final_state_reconciliation_verified": True,
        "terminal_order_rest_verified": True,
        "account_trades_rest_verified": True,
        "final_user_stream_journals_verified": True,
        "action_time_collateral_verified": True,
        "no_fill_collateral_reconciliation_verified": True,
        "cancel_all_request_verified": True,
        "cancel_all_zero_open_orders_verified": True,
        "dead_man_automatic_cancel_verified": True,
        "heartbeat_acknowledgment_verified": True,
    }
    assert len(bundle["bundle_sha256"]) == 64
    assert SCHEMA_VERSION == "mm_live_lifecycle_probe_v0.3"
    assert JOURNAL_SCHEMA_VERSION == "mm_live_lifecycle_probe_journal_v0.2"
    assert LIFECYCLE_BUNDLE_SCHEMA_VERSION == "mm_stage1_lifecycle_bundle_v0.3"

    oversized_result = dict(cancel_result)
    oversized_result["order_notional_usdc"] = 10.01
    with pytest.raises(RuntimeError, match="notional"):
        build_stage1_lifecycle_bundle(gate, oversized_result, dead_result)

    unreconciled_result = dict(cancel_result)
    unreconciled_result["post_cancel_collateral_snapshot_sha256"] = "0" * 64
    with pytest.raises(RuntimeError, match="collateral_reconciliation"):
        build_stage1_lifecycle_bundle(gate, unreconciled_result, dead_result)

    cleanup_hash_tamper = dict(cancel_result)
    cleanup_hash_tamper["cleanup_final_user_stream_journal_sha256"] = "0" * 64
    with pytest.raises(RuntimeError, match="cleanup final user-stream journal hash"):
        build_stage1_lifecycle_bundle(gate, cleanup_hash_tamper, dead_result)

    stale_rules_result = dict(cancel_result)
    stale_rules_result["current_fee_rate_bps"] = 499
    with pytest.raises(RuntimeError, match="action_time_market_rules"):
        build_stage1_lifecycle_bundle(gate, stale_rules_result, dead_result)

    incomplete_stream_result = dict(cancel_result)
    incomplete_stream_result["user_stream_journal_row_count"] = 0
    with pytest.raises(RuntimeError, match="final user-stream journal counts"):
        build_stage1_lifecycle_bundle(gate, incomplete_stream_result, dead_result)

    legacy_result = dict(cancel_result)
    legacy_result["schema_version"] = "mm_live_lifecycle_probe_v0.2"
    with pytest.raises(RuntimeError, match="schema"):
        build_stage1_lifecycle_bundle(gate, legacy_result, dead_result)

    lifecycle_path = Path(cancel_result["journal_path"])
    current_journal = lifecycle_path.read_bytes()
    legacy_rows = [
        {**json.loads(line), "schema_version": "mm_live_lifecycle_probe_journal_v0.1"}
        for line in current_journal.decode("utf-8").splitlines()
        if line
    ]
    lifecycle_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in legacy_rows),
        encoding="utf-8",
    )
    legacy_journal_result = dict(cancel_result)
    legacy_journal_result["journal_sha256"] = hashlib.sha256(
        lifecycle_path.read_bytes()
    ).hexdigest()
    with pytest.raises(RuntimeError, match="journal schema"):
        build_stage1_lifecycle_bundle(gate, legacy_journal_result, dead_result)
    lifecycle_path.write_bytes(current_journal)

    Path(cancel_result["user_stream_journal_path"]).write_text(
        "{}\n", encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="journal schema|journal hash"):
        build_stage1_lifecycle_bundle(gate, cancel_result, dead_result)


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
    attach_stream_journal(cancel_result, tmp_path / "cancel-all-stream.jsonl")
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
    attach_stream_journal(dead_result, tmp_path / "dead-man-stream.jsonl")
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
    attach_stream_journal(cancel_result, tmp_path / "cancel-all-stream.jsonl")
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
    attach_stream_journal(dead_result, tmp_path / "dead-man-stream.jsonl")
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



@pytest.mark.parametrize("balance,allowance,allocation", [
    ("9999999", "100000000", 100),
    ("275480000", "9999999", 100),
    ("275480000", "100000000", 100.01),
    ("NaN", "100000000", 100),
])
def test_existing_wallet_action_time_capital_refusal_prevents_submission(
    tmp_path, balance, allowance, allocation
):
    gate = bootstrap_gate()
    gate.update(
        pilot_capital_mode="existing_wallet_test_allocation",
        pilot_test_allocation_pusd=allocation,
        isolated_pilot_wallet=False,
        pilot_wallet_max_funding_usdc=None,
    )
    clock = FakeClock()
    adapter = FakeAdapter(clock)
    adapter.collateral_payloads = [
        {"balance": balance, "allowances": {"exchange": allowance}}
    ]
    with pytest.raises(RuntimeError):
        execute_stage1_lifecycle_probe(
            adapter, gate, confirmation=CONFIRMATION, cancellation_mode="cancel_all",
            journal_path=tmp_path / "allocation-rejected.jsonl",
            monotonic_clock=clock, sleeper=clock.sleep,
        )
    assert adapter.place_calls == 0
