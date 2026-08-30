import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from weather.market import mm_live_pilot_cli as cli
from weather.market import mm_live_candidate_cli as candidate_cli
from weather.market import mm_geographic_eligibility as geography
from weather.market.mm_credentials import STAGE0_AUTHORIZATION
from weather.market.mm_live_lifecycle_probe import CONFIRMATION as STAGE1_CONFIRMATION


ADDRESS = "0x" + "a" * 40
CONDITION_ID = "0x" + "b" * 64
TOKEN_ID = "12345"


def write_geography_receipt(path: Path, checked: datetime) -> Path:
    current = checked.astimezone(timezone.utc)
    decision = {"blocked": False, "country": "GB", "region": "ENG"}
    payload = {
        "agreement": True,
        "blocker_code": None,
        "checked_at_utc": geography._iso_utc(current),
        "eligible": True,
        "endpoint": geography.GEOBLOCK_ENDPOINT,
        "fresh_until_utc": geography._iso_utc(
            current + timedelta(seconds=geography.MAX_RECEIPT_AGE_SECONDS)
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
    payload["receipt_payload_sha256"] = geography._payload_digest(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class FakeStream:
    def __init__(self, journal_path):
        self.started = False
        self.stopped = False
        self.rows = []
        self.journal_path = Path(journal_path)

    def start(self):
        self.started = True
        self.journal_path.write_text(
            '{"schema_version":"mm_user_stream_journal_v0.1",'
            '"event_type":"subscription_sent"}\n',
            encoding="utf-8",
        )

    def stop(self):
        self.stopped = True
        with self.journal_path.open("a", encoding="utf-8") as handle:
            handle.write(
                '{"schema_version":"mm_user_stream_journal_v0.1",'
                '"event_type":"stream_stopped"}\n'
            )

    def bootstrap_evidence(self):
        return {
            "account_wide_subscription_sent": self.started,
            "server_pong_observed": self.started,
            "transport_active": self.started and not self.stopped,
            "transport_state": (
                "STOPPED" if self.stopped else "TRANSPORT_CONNECTED_UNPROVEN"
            ),
            "journal_sha256": hashlib.sha256(self.journal_path.read_bytes()).hexdigest(),
        }

    def health(self):
        return {
            "state": "STOPPED" if self.stopped else "TRANSPORT_CONNECTED_UNPROVEN",
            "failure_type": None,
        }

    def events(self):
        return list(self.rows)


class FakeAdapter:
    maker_address = ADDRESS
    condition_id = CONDITION_ID

    def __init__(self):
        self.cancel_calls = 0

    def cancel_all(self):
        self.cancel_calls += 1
        return {"canceled": []}

    def open_orders(self):
        return []

    def positions(self):
        return []

    def position_evidence(self, positions):
        return {
            "status": "OBSERVED",
            "query_scope": "exact_maker_condition",
            "maker_address": ADDRESS,
            "condition_id": CONDITION_ID,
            "request_url": (
                "https://data-api.polymarket.com/positions?"
                f"user={ADDRESS}&market={CONDITION_ID}&sizeThreshold=0&limit=500&offset=0"
            ),
            "http_status": 200,
            "response_sha256": "c" * 64,
            "rows": list(positions),
        }


class FakeClient:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def context(tmp_path, name="context-stream.jsonl"):
    stream = FakeStream(tmp_path / name)
    adapter = FakeAdapter()
    return cli.LivePilotContext(
        credentials=object(),
        client=FakeClient(),
        user_stream=stream,
        adapter=adapter,
        credential_topology={
            "manifest_wallet_address": ADDRESS,
            "derived_signer_matches_manifest": True,
            "api_owner_matches_manifest": True,
            "order_signer_matches_manifest": True,
            "funder_matches_identity": True,
        },
    )


def args(tmp_path, command):
    identity = tmp_path / "identity.json"
    identity.write_text(json.dumps({"public": "identity"}), encoding="utf-8")
    common = {
        "command": command,
        "identity": str(identity),
        "target_date": "2026-08-14",
        "condition_id": CONDITION_ID,
        "token_id": TOKEN_ID,
        "budget": 10.0,
        "expected_wallet_address": ADDRESS,
        "credential_resolution_deadline_utc": "2099-01-01T00:00:00+00:00",
        "user_stream_journal": str(tmp_path / f"{command}-stream.jsonl"),
        "receipt_out": str(tmp_path / f"{command}-receipt.json"),
        "user_stream_ready_timeout_seconds": 5.0,
    }
    if command == "stage0":
        geography_premutation = tmp_path / "stage0-geography-premutation.json"

        def pre_mutation_attestor():
            write_geography_receipt(
                geography_premutation,
                datetime.now(timezone.utc),
            )
            return json.loads(geography_premutation.read_text(encoding="utf-8"))

        common.update(
            confirmation=STAGE0_AUTHORIZATION,
            bootstrap_out=str(tmp_path / "bootstrap.json"),
            geography_premutation_receipt=str(geography_premutation),
            expected_candidate_fee_rate=0.05,
            expected_candidate_neg_risk=False,
            pre_mutation_attestor=pre_mutation_attestor,
        )
    else:
        bootstrap = tmp_path / "bootstrap-input.json"
        bootstrap.write_text("{}", encoding="utf-8")
        candidate = tmp_path / "stage1-candidate.json"
        current = datetime.now(timezone.utc)
        paper_generated = current - timedelta(seconds=2)
        created = current - timedelta(seconds=1)
        paper_expires = paper_generated + timedelta(seconds=120)
        economics_hash = "c" * 32
        economics_id = f"xecon-{economics_hash[:16]}"
        accepted_file_hash = "a" * 64
        drift_file_hash = "b" * 64
        economics_acknowledgment = (
            candidate_cli.economics_acceptance_acknowledgment(
                "2026-08-14",
                CONDITION_ID,
                TOKEN_ID,
                accepted_snapshot_file_sha256=accepted_file_hash,
                drift_report_file_sha256=drift_file_hash,
            )
        )
        candidate_payload = {
            "schema_version": candidate_cli.SCHEMA_VERSION,
            "status": "PASS",
            "created_at_utc": created.isoformat(),
            "expires_at_utc": paper_expires.isoformat(),
            "target_date": "2026-08-14",
            "platform": candidate_cli.PLATFORM,
            "settlement_unit": candidate_cli.SETTLEMENT_UNIT,
            "exchange_economics_snapshot_id": economics_id,
            "exchange_economics_sha256": economics_hash,
            "economics_gate_ok": True,
            "economics_gate_missing": [],
            "economics_acceptance": {
                "accepted_at_utc": (current - timedelta(seconds=3)).isoformat(),
                "accepted_snapshot_file_sha256": accepted_file_hash,
                "accepted_snapshot_id": economics_id,
                "accepted_snapshot_sha256": economics_hash,
                "drift_generated_at_utc": (
                    current - timedelta(seconds=3)
                ).isoformat(),
                "drift_report_file_sha256": drift_file_hash,
                "drift_status": "PASS",
                "operator_acknowledgment": economics_acknowledgment,
                "operator_acknowledgment_matches_candidate": True,
                "required_operator_acknowledgment": economics_acknowledgment,
                "rescore_required": False,
            },
            "substrate_preflight": {
                "schema_version": candidate_cli.SUBSTRATE_PREFLIGHT_SCHEMA_VERSION,
                "receipt_sha256": "0" * 64,
                "checked_at_utc": (current - timedelta(seconds=3)).isoformat(),
                "expires_at_utc": (
                    current
                    - timedelta(seconds=3)
                    + timedelta(
                        seconds=candidate_cli.MAX_SUBSTRATE_PREFLIGHT_AGE_SECONDS
                    )
                ).isoformat(),
                "market_id": "toronto",
                "target_date": "2026-08-14",
                "event_slug": "toronto-high-temperature-test",
                "validation_hash": "1" * 64,
                "event_metadata_file_sha256": "2" * 64,
                "event_metadata_validation_file_sha256": "3" * 64,
                "observation_status_file_sha256": "4" * 64,
                "economics_snapshot_file_sha256": "5" * 64,
                "accepted_snapshot_file_sha256": accepted_file_hash,
                "economics_drift_report_file_sha256": drift_file_hash,
                "paper_run_config_file_sha256": "d" * 64,
                "paper_preflight_file_sha256": "6" * 64,
                "paper_quote_intents_file_sha256": "e" * 64,
                "clob_tokens_file_sha256": "7" * 64,
                "order_books_summary_file_sha256": "8" * 64,
                "source_status_long_file_sha256": "9" * 64,
                "network_access": False,
                "credential_access": False,
                "exchange_contact": False,
                "exchange_mutation": False,
            },
            "selection_is_trading_authorization": False,
            "secret_values_retained": False,
            "selection_policy": {
                "built_in_locations_only": True,
                "positive_fee_and_rebate_required": True,
                "midpoint_interval": [
                    float(candidate_cli.MIN_MIDPOINT),
                    float(candidate_cli.MAX_MIDPOINT),
                ],
                "max_spread": float(candidate_cli.MAX_BOOK_SPREAD),
                "minimum_tick_buy_must_be_nonmarketable": True,
                "book_tick_min_size_and_neg_risk_must_be_current": True,
                "plan_max_age_seconds": candidate_cli.MAX_PLAN_AGE_SECONDS,
                "max_single_order_notional_pusd": float(
                    candidate_cli.MAX_SINGLE_ORDER_NOTIONAL
                ),
                "successful_current_market_harvest_quote_required": True,
                "expected_bootstrap_scope": {
                    "condition_id": CONDITION_ID,
                    "token_id": TOKEN_ID,
                },
                "ranking": "spread_asc_then_best_level_depth_desc_then_midpoint_distance",
            },
            "paper_quote_evidence": {
                "run_config_sha256": "d" * 64,
                "quote_intents_sha256": "e" * 64,
                "quote_intents_row_count": 1,
                "run_id": "paper-run-1",
                "market_id": "toronto",
            },
            "candidate_count": 1,
            "selected": {
                "location_id": "toronto",
                "event_date": "2026-08-14",
                "event_slug": "toronto-high-temperature-test",
                "question": "Will Toronto reach the selected high-temperature range?",
                "condition_id": CONDITION_ID,
                "token_id": TOKEN_ID,
                "outcome_index": 0,
                "best_bid": 0.49,
                "best_ask": 0.50,
                "midpoint": 0.495,
                "spread": 0.01,
                "best_bid_depth": 100.0,
                "best_ask_depth": 100.0,
                "tick_size": 0.01,
                "order_min_size": 5.0,
                "neg_risk": False,
                "fee_rate": 0.05,
                "maker_rebate_rate": 0.25,
                "reward_min_size": 20.0,
                "reward_max_spread_cents": 4.5,
                "current_book_within_reward_spread": True,
                "lifecycle_probe_reward_min_size_met": False,
                "book_sha256": "c" * 64,
                "stage1_intent": {
                    "side": "BUY",
                    "price": 0.01,
                    "size": 5.0,
                    "notional_pusd": 0.05,
                    "post_only": True,
                },
                "paper_quote_proof": {
                    "run_id": "paper-run-1",
                    "market_id": "toronto",
                    "target_date": "2026-08-14",
                    "condition_id": CONDITION_ID,
                    "token_id": TOKEN_ID,
                    "range_label": "test-range",
                    "exchange_economics_snapshot_id": economics_id,
                    "exchange_economics_hash": economics_hash,
                    "policy_hash": "paper-policy-hash",
                    "generated_at_utc": paper_generated.isoformat(),
                    "expires_at_utc": paper_expires.isoformat(),
                    "quote_ttl_seconds": 120,
                    "bid_price": 0.48,
                    "bid_size": 5.0,
                    "ask_price": 0.51,
                    "ask_size": 5.0,
                    "quote_risk_pusd": 4.85,
                    "quote_permission": True,
                    "live_trade_permission": False,
                    "two_sided_post_only_intent": True,
                    "reward_and_rebate_assumed_zero": True,
                    "quote_row_sha256": "f" * 64,
                },
            },
            "alternates": [],
            "missing": [],
        }
        candidate_payload["plan_sha256"] = candidate_cli.candidate_plan_sha256(
            candidate_payload
        )
        candidate.write_text(json.dumps(candidate_payload), encoding="utf-8")
        common.update(
            confirmation=STAGE1_CONFIRMATION,
            bootstrap=str(bootstrap),
            candidate_plan=str(candidate),
            cancellation_mode="cancel_all",
            submit_deadline_utc=(current + timedelta(minutes=2)).isoformat(),
            pre_submit_attestor=lambda: {},
            lifecycle_journal=str(tmp_path / "lifecycle.jsonl"),
            result_out=str(tmp_path / "stage1-result.json"),
        )
    return SimpleNamespace(**common)


def prepare_args(tmp_path):
    return SimpleNamespace(
        command="prepare-identity",
        funder_address=ADDRESS,
        wallet_type="deposit_wallet",
        signature_type="POLY_1271",
        budget=10.0,
        wallet_cap=100.0,
        identity_out=str(tmp_path / "identity-prepared.json"),
        receipt_out=str(tmp_path / "identity-receipt.json"),
        confirm_international_platform=True,
        confirm_isolated_wallet=True,
        confirmation=cli.IDENTITY_CONFIRMATION,
    )


def doctor_args(tmp_path, identity_path):
    return SimpleNamespace(
        command="doctor",
        identity=str(identity_path),
        target_date="2026-08-14",
        condition_id=CONDITION_ID,
        token_id=TOKEN_ID,
        budget=10.0,
        receipt_out=str(tmp_path / "doctor-receipt.json"),
        confirmation=cli.DOCTOR_CONFIRMATION,
    )


def credential_reference_env():
    return {
        "POLYMARKET_API_KEY_STORAGE_REF": "wincred://Weather/Pilot/ApiKey",
        "POLYMARKET_API_SECRET_STORAGE_REF": "wincred://Weather/Pilot/ApiSecret",
        "POLYMARKET_API_PASSPHRASE_STORAGE_REF": "wincred://Weather/Pilot/Passphrase",
        "POLYMARKET_PRIVATE_KEY_STORAGE_REF": "wincred://Weather/Pilot/PrivateKey",
        "POLYMARKET_FUNDER_ADDRESS": ADDRESS,
    }


def test_prepare_identity_derives_signature_id(tmp_path):
    command_args = prepare_args(tmp_path)

    receipt = cli.run_prepare_identity(command_args)

    assert receipt["status"] == "PASS"
    identity = json.loads(Path(command_args.identity_out).read_text(encoding="utf-8"))
    assert identity["platform"] == "polymarket_global"
    assert identity["settlement_unit"] == "pUSD"
    assert identity["signature_type"] == "POLY_1271"
    assert identity["signature_type_id"] == 3
    assert identity["pilot_wallet_max_funding_usdc"] == 100.0
    assert receipt["requested_budget_pusd"] == 10.0
    assert receipt["cleanup"]["reason"] == "read_only_command_no_exchange_authentication"


def test_prepare_identity_keeps_requested_budget_below_independent_wallet_cap(tmp_path):
    command_args = prepare_args(tmp_path)
    command_args.budget = 100.0
    command_args.wallet_cap = 10.0

    with pytest.raises(RuntimeError, match="10 pUSD.*100 pUSD"):
        cli.run_prepare_identity(command_args)

    assert not Path(command_args.identity_out).exists()
    assert not Path(command_args.receipt_out).exists()
@pytest.mark.parametrize(
    ("wallet_type", "signature_type", "missing_check"),
    [
        ("eoa", "POLY_1271", "pilot_wallet_signature_topology"),
        ("deposit_wallet", "EOA", "pilot_wallet_signature_topology"),
        ("gnosis_safe", "POLY_1271", "pilot_wallet_signature_topology"),
    ],
)
def test_prepare_identity_rejects_non_deposit_wallet_topology(
    tmp_path,
    wallet_type,
    signature_type,
    missing_check,
):
    command_args = prepare_args(tmp_path)
    command_args.wallet_type = wallet_type
    command_args.signature_type = signature_type

    with pytest.raises(RuntimeError, match="did not pass"):
        cli.run_prepare_identity(command_args)

    receipt = json.loads(Path(command_args.receipt_out).read_text(encoding="utf-8"))
    assert receipt["status"] == "FAIL"
    assert missing_check in receipt["missing"]
    assert not Path(command_args.identity_out).exists()


def test_prepare_identity_accepts_existing_gnosis_safe_topology(tmp_path):
    command_args = prepare_args(tmp_path)
    command_args.wallet_type = "gnosis_safe"
    command_args.signature_type = "POLY_GNOSIS_SAFE"

    receipt = cli.run_prepare_identity(command_args)

    identity = json.loads(Path(command_args.identity_out).read_text(encoding="utf-8"))
    assert receipt["status"] == "PASS"
    assert identity["wallet_type"] == "gnosis_safe"
    assert identity["signature_type"] == "POLY_GNOSIS_SAFE"
    assert identity["signature_type_id"] == 2


def test_prepare_identity_wrong_confirmation_writes_nothing(tmp_path):
    command_args = prepare_args(tmp_path)
    command_args.confirmation = "yes"

    with pytest.raises(RuntimeError, match="exact confirmation"):
        cli.run_prepare_identity(command_args)

    assert not Path(command_args.identity_out).exists()
    assert not Path(command_args.receipt_out).exists()


def test_keyless_doctor_passes_without_resolving_credential_targets(tmp_path):
    prepare = prepare_args(tmp_path)
    cli.run_prepare_identity(prepare)
    command_args = doctor_args(tmp_path, prepare.identity_out)
    env = credential_reference_env()

    receipt = cli.run_doctor(
        command_args,
        env=env,
        sdk_version_getter=lambda: "0.6.0",
        platform_name="nt",
    )

    assert receipt["status"] == "PASS"
    assert receipt["missing"] == []
    assert receipt["credential_reference_present_count"] == 4
    raw = Path(command_args.receipt_out).read_text(encoding="utf-8")
    assert "Weather/Pilot" not in raw
    assert "wincred://" not in raw


def test_keyless_doctor_names_missing_sdk_and_reference_without_reading_secrets(tmp_path):
    prepare = prepare_args(tmp_path)
    cli.run_prepare_identity(prepare)
    command_args = doctor_args(tmp_path, prepare.identity_out)
    env = credential_reference_env()
    del env["POLYMARKET_API_SECRET_STORAGE_REF"]

    with pytest.raises(RuntimeError, match="blocking setup checks"):
        cli.run_doctor(
            command_args,
            env=env,
            sdk_version_getter=lambda: None,
            platform_name="nt",
        )

    raw = Path(command_args.receipt_out).read_text(encoding="utf-8")
    receipt = json.loads(raw)
    assert receipt["status"] == "FAIL"
    assert "credential_reference_variables_complete" in receipt["missing"]
    assert "credential_reference_shapes_valid" in receipt["missing"]
    assert "official_sdk_exact_version_installed" in receipt["missing"]
    assert receipt["credential_reference_present_count"] == 3
    assert "Weather/Pilot" not in raw


def test_stage0_boundary_writes_bootstrap_only_after_zero_state_cleanup(tmp_path):
    command_args = args(tmp_path, "stage0")
    live_context = context(tmp_path)
    seen = {}

    def collect(_adapter, stream, *_args, **kwargs):
        seen.update(kwargs)
        geography_receipt = kwargs["pre_mutation_attestor"]()
        return {
            "schema_version": "mm_platform_bootstrap_v0.4",
            "status": "PASS",
            "secret_values_redacted": True,
            "user_stream": stream.bootstrap_evidence(),
            "mutation_geographic_eligibility": {
                "receipt_payload_sha256": geography_receipt[
                    "receipt_payload_sha256"
                ]
            },
        }

    receipt = cli.run_stage0(
        command_args,
        context_builder=lambda *_args, **_kwargs: live_context,
        stream_waiter=lambda stream, **_kwargs: stream.start(),
        bootstrap_collector=collect,
    )

    assert receipt["status"] == "PASS"
    assert live_context.adapter.cancel_calls == 0
    assert live_context.user_stream.stopped
    assert json.loads(open(command_args.bootstrap_out, encoding="utf-8").read())["status"] == "PASS"
    saved_receipt = json.loads(open(command_args.receipt_out, encoding="utf-8").read())
    assert saved_receipt["cleanup"]["zero_open_orders_verified"] is True
    assert saved_receipt["cleanup"]["zero_positions_verified"] is True
    assert saved_receipt["cleanup"]["cancel_all_required"] is False
    assert saved_receipt["cleanup"]["cancel_all_sent"] is False
    assert saved_receipt["credential_resolution_attempted"] is True
    assert saved_receipt["credential_values_read_in_memory"] is True
    assert saved_receipt["exchange_mutation_attempted"] is True
    assert saved_receipt["authenticated_exchange_write_attempted"] is True
    assert saved_receipt["order_submit_attempted"] is False
    final_sha256 = hashlib.sha256(live_context.user_stream.journal_path.read_bytes()).hexdigest()
    assert saved_receipt["cleanup"]["user_stream_journal_sha256"] == final_sha256
    assert saved_receipt["secret_values_redacted"] is True
    saved_bootstrap = json.loads(open(command_args.bootstrap_out, encoding="utf-8").read())
    assert saved_bootstrap["user_stream"]["transport_active_at_collection"] is True
    assert saved_bootstrap["user_stream"]["transport_stopped_cleanly_after_collection"] is True
    assert saved_bootstrap["user_stream"]["journal_sha256_at_collection"] != final_sha256
    assert saved_bootstrap["user_stream"]["journal_sha256"] == final_sha256
    assert seen["expected_candidate_fee_rate"] == 0.05
    assert seen["expected_candidate_neg_risk"] is False
    assert callable(seen["pre_mutation_attestor"])
    assert saved_receipt["mutation_geographic_eligibility"]["path"] == str(
        Path(command_args.geography_premutation_receipt).resolve()
    )


def test_retired_stage0_read_only_literal_stops_before_credential_resolution(
    tmp_path,
):
    command_args = args(tmp_path, "stage0")
    command_args.confirmation = "INTERNATIONAL_POLYMARKET_STAGE0_READ_ONLY"
    context_calls = []

    with pytest.raises(
        RuntimeError,
        match="exact heartbeat/account-wide-cancel-all/no-order confirmation token",
    ):
        cli.run_stage0(
            command_args,
            context_builder=lambda *_args, **_kwargs: context_calls.append(True),
        )

    assert context_calls == []
    assert not Path(command_args.bootstrap_out).exists()
    assert not Path(command_args.receipt_out).exists()
    assert not Path(command_args.user_stream_journal).exists()


def test_stage0_keyboard_interrupt_still_cleans_up_and_writes_redacted_receipt(
    tmp_path,
):
    command_args = args(tmp_path, "stage0")
    live_context = context(tmp_path)

    def interrupt_after_authentication(*_args, **_kwargs):
        raise KeyboardInterrupt("RAW-STAGE0-INTERRUPT-TEXT")

    with pytest.raises(KeyboardInterrupt, match="RAW-STAGE0-INTERRUPT-TEXT"):
        cli.run_stage0(
            command_args,
            context_builder=lambda *_args, **_kwargs: live_context,
            stream_waiter=lambda stream, **_kwargs: stream.start(),
            bootstrap_collector=interrupt_after_authentication,
        )

    raw = Path(command_args.receipt_out).read_text(encoding="utf-8")
    receipt = json.loads(raw)
    assert receipt["status"] == "FAIL"
    assert receipt["exception_type"] == "KeyboardInterrupt"
    assert receipt["cleanup"]["ok"] is True
    assert "RAW-STAGE0-INTERRUPT-TEXT" not in raw
    assert live_context.adapter.cancel_calls == 0
    assert live_context.user_stream.stopped is True
    assert live_context.client.closed is True
    assert not Path(command_args.bootstrap_out).exists()


def test_stage1_boundary_writes_result_after_exact_gate_and_final_cleanup(tmp_path):
    command_args = args(tmp_path, "stage1")
    live_context = context(tmp_path, "stage1-stream.jsonl")
    seen = {}

    def execute(adapter, gate, **kwargs):
        seen.update(gate=gate, kwargs=kwargs)
        kwargs["journal_path"].write_text('{"event_type":"probe_passed"}\n', encoding="utf-8")
        with live_context.user_stream.journal_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "schema_version": "mm_user_stream_journal_v0.1",
                "event_type": "user_event",
                "payload": {
                    "id": "order-1",
                    "type": "CANCELLATION",
                    "status": "CANCELED",
                    "size_matched": "0",
                },
            }) + "\n")
        return {
            "schema_version": "mm_live_lifecycle_probe_v0.3",
            "status": "PASS",
            "order_id": "order-1",
            "secret_values_redacted": True,
        }

    receipt = cli.run_stage1(
        command_args,
        context_builder=lambda *_args, **_kwargs: live_context,
        stream_waiter=lambda stream, **_kwargs: stream.start(),
        bootstrap_loader=lambda *_args, **_kwargs: {
            "ok": True,
            "platform": "polymarket_global",
        },
        lifecycle_executor=execute,
    )

    assert receipt["status"] == "PASS"
    assert seen["kwargs"]["confirmation"] == STAGE1_CONFIRMATION
    assert seen["kwargs"]["cancellation_mode"] == "cancel_all"
    assert seen["kwargs"]["submit_deadline_utc"] == command_args.submit_deadline_utc
    assert seen["kwargs"]["expected_candidate_fee_rate"] == 0.05
    assert seen["kwargs"]["expected_candidate_neg_risk"] is False
    assert live_context.adapter.cancel_calls == 0
    assert live_context.user_stream.stopped
    saved_result = json.loads(open(command_args.result_out, encoding="utf-8").read())
    assert saved_result["status"] == "PASS"
    assert len(saved_result["candidate_plan_sha256"]) == 64
    assert saved_result["paper_run_config_sha256"] == "d" * 64
    assert saved_result["paper_quote_intents_sha256"] == "e" * 64
    assert saved_result["paper_quote_row_sha256"] == "f" * 64
    saved_receipt = json.loads(Path(command_args.receipt_out).read_text(encoding="utf-8"))
    assert saved_receipt["credential_values_read_in_memory"] is True


def test_stage1_failure_receipt_never_serializes_raw_exception_text(tmp_path):
    command_args = args(tmp_path, "stage1")
    live_context = context(tmp_path)

    with pytest.raises(RuntimeError, match="TOP-SECRET-SDK-TEXT"):
        cli.run_stage1(
            command_args,
            context_builder=lambda *_args, **_kwargs: live_context,
            stream_waiter=lambda stream, **_kwargs: stream.start(),
            bootstrap_loader=lambda *_args, **_kwargs: {"ok": True},
            lifecycle_executor=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("TOP-SECRET-SDK-TEXT")
            ),
        )

    raw = open(command_args.receipt_out, encoding="utf-8").read()
    receipt = json.loads(raw)
    assert receipt["status"] == "FAIL"
    assert receipt["exception_type"] == "RuntimeError"
    assert "TOP-SECRET-SDK-TEXT" not in raw
    assert live_context.adapter.cancel_calls == 1
    assert receipt["authenticated_exchange_write_attempted"] is True
    assert receipt["exchange_mutation_attempted"] is True
    assert receipt["order_submit_attempted"] is False


def test_stage1_failure_after_submit_start_records_order_attempt(tmp_path):
    command_args = args(tmp_path, "stage1")
    live_context = context(tmp_path)

    def fail_after_submit(*_args, journal_path, **_kwargs):
        Path(journal_path).write_text(
            '{"event_type":"submit_started"}\n', encoding="utf-8"
        )
        raise RuntimeError("post-submit failure")

    with pytest.raises(RuntimeError, match="post-submit failure"):
        cli.run_stage1(
            command_args,
            context_builder=lambda *_args, **_kwargs: live_context,
            stream_waiter=lambda stream, **_kwargs: stream.start(),
            bootstrap_loader=lambda *_args, **_kwargs: {"ok": True},
            lifecycle_executor=fail_after_submit,
        )

    receipt = json.loads(Path(command_args.receipt_out).read_text())
    assert receipt["authenticated_exchange_write_attempted"] is True
    assert receipt["order_submit_attempted"] is True


def test_stage1_keyboard_interrupt_still_cleans_up_and_writes_redacted_receipt(
    tmp_path,
):
    command_args = args(tmp_path, "stage1")
    live_context = context(tmp_path)

    def interrupt_after_context(*_args, **_kwargs):
        raise KeyboardInterrupt("RAW-STAGE1-INTERRUPT-TEXT")

    with pytest.raises(KeyboardInterrupt, match="RAW-STAGE1-INTERRUPT-TEXT"):
        cli.run_stage1(
            command_args,
            context_builder=lambda *_args, **_kwargs: live_context,
            stream_waiter=lambda stream, **_kwargs: stream.start(),
            bootstrap_loader=lambda *_args, **_kwargs: {"ok": True},
            lifecycle_executor=interrupt_after_context,
        )

    raw = Path(command_args.receipt_out).read_text(encoding="utf-8")
    receipt = json.loads(raw)
    assert receipt["status"] == "FAIL"
    assert receipt["exception_type"] == "KeyboardInterrupt"
    assert receipt["cleanup"]["ok"] is True
    assert "RAW-STAGE1-INTERRUPT-TEXT" not in raw
    assert live_context.adapter.cancel_calls == 1
    assert live_context.user_stream.stopped is True
    assert live_context.client.closed is True
    assert not Path(command_args.result_out).exists()


def test_cleanup_context_continues_after_interrupting_cancel_all(tmp_path):
    live_context = context(tmp_path)
    live_context.user_stream.start()

    def interrupting_cancel_all():
        raise KeyboardInterrupt("RAW-CLEANUP-INTERRUPT-TEXT")

    live_context.adapter.cancel_all = interrupting_cancel_all
    outcome = cli._cleanup_context(live_context)

    assert outcome["ok"] is False
    assert outcome["exception_type"] == "KeyboardInterrupt"
    assert outcome["user_stream_stopped"] is True
    assert outcome["client_closed"] is True
    assert live_context.user_stream.stopped is True
    assert live_context.client.closed is True


def test_stage1_rejects_candidate_gate_before_credentials_or_mutation(tmp_path):
    command_args = args(tmp_path, "stage1")
    context_called = False

    def build(*_args, **_kwargs):
        nonlocal context_called
        context_called = True
        return context(tmp_path)

    with pytest.raises(RuntimeError, match="paper proof missing"):
        cli.run_stage1(
            command_args,
            context_builder=build,
            candidate_loader=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("paper proof missing")
            ),
            bootstrap_loader=lambda *_args, **_kwargs: {"ok": True},
        )

    assert context_called is False
    receipt = json.loads(Path(command_args.receipt_out).read_text(encoding="utf-8"))
    assert receipt["status"] == "FAIL"
    assert receipt["exception_type"] == "RuntimeError"
    assert "paper proof missing" not in Path(command_args.receipt_out).read_text(
        encoding="utf-8"
    )


def test_stage1_result_write_failure_still_emits_fail_receipt(
    tmp_path,
    monkeypatch,
):
    command_args = args(tmp_path, "stage1")
    live_context = context(tmp_path, "stage1-stream.jsonl")
    real_writer = cli.write_json_atomic

    def writer(path, payload, **kwargs):
        if Path(path) == Path(command_args.result_out):
            raise OSError("RAW-RESULT-WRITE-DETAIL")
        return real_writer(path, payload, **kwargs)

    def execute(_adapter, _gate, **kwargs):
        kwargs["journal_path"].write_text(
            '{"event_type":"submit_started"}\n'
            '{"event_type":"probe_passed"}\n',
            encoding="utf-8",
        )
        with live_context.user_stream.journal_path.open(
            "a", encoding="utf-8"
        ) as handle:
            handle.write(
                json.dumps(
                    {
                        "schema_version": "mm_user_stream_journal_v0.1",
                        "event_type": "user_event",
                        "payload": {
                            "id": "order-1",
                            "type": "CANCELLATION",
                            "status": "CANCELED",
                            "size_matched": "0",
                        },
                    }
                )
                + "\n"
            )
        return {
            "schema_version": "mm_live_lifecycle_probe_v0.3",
            "status": "PASS",
            "order_id": "order-1",
            "secret_values_redacted": True,
        }

    monkeypatch.setattr(cli, "write_json_atomic", writer)

    with pytest.raises(OSError, match="RAW-RESULT-WRITE-DETAIL"):
        cli.run_stage1(
            command_args,
            context_builder=lambda *_args, **_kwargs: live_context,
            stream_waiter=lambda stream, **_kwargs: stream.start(),
            bootstrap_loader=lambda *_args, **_kwargs: {"ok": True},
            lifecycle_executor=execute,
        )

    raw = Path(command_args.receipt_out).read_text(encoding="utf-8")
    receipt = json.loads(raw)
    assert receipt["status"] == "FAIL"
    assert receipt["exception_type"] == "OSError"
    assert receipt["order_submit_attempted"] is True
    assert receipt["cleanup"]["ok"] is True
    assert receipt["cleanup"]["user_stream_stopped"] is True
    assert receipt["cleanup"]["client_closed"] is True
    assert "RAW-RESULT-WRITE-DETAIL" not in raw
    assert not Path(command_args.result_out).exists()
    assert live_context.user_stream.stopped is True
    assert live_context.client.closed is True


def test_offline_bundle_command_binds_both_results_without_exchange_cleanup(tmp_path):
    command_args = args(tmp_path, "stage1")
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    cancel_result = attempt / "stage1-cancel-all/result.json"
    dead_result = attempt / "stage1-dead-man/result.json"
    cancel_result.parent.mkdir(parents=True)
    dead_result.parent.mkdir(parents=True)
    command_args.expected_production_tip = "a" * 40
    command_args.command = "bundle"
    command_args.confirmation = cli.BUNDLE_CONFIRMATION
    command_args.cancel_all_result = str(cancel_result)
    command_args.dead_man_result = str(dead_result)
    command_args.bundle_out = str(tmp_path / "bundle.json")
    command_args.receipt_out = str(tmp_path / "bundle-receipt.json")
    def add_lineage(mode, result_path):
        stage = "stage1_cancel_all" if mode == "cancel_all" else "stage1_dead_man"
        prefix = "cancel_all" if mode == "cancel_all" else "dead_man"
        stage_folder = "stage1-cancel-all" if mode == "cancel_all" else "stage1-dead-man"
        wrapper = attempt / "wrappers" / f"{stage_folder}.py"
        wrapper.parent.mkdir(parents=True, exist_ok=True)
        wrapper.write_text("# sealed wrapper\n", encoding="utf-8")
        launcher = attempt / "wrappers" / f"{stage_folder}.ps1"
        launcher.write_text("# sealed launcher\n", encoding="utf-8")
        journal = attempt / stage_folder / "lifecycle.jsonl"
        journal.write_text('{"event_type":"probe_passed"}\n', encoding="utf-8")
        stream = attempt / stage_folder / "user-stream.jsonl"
        order_id = f"{mode}-order"
        stream.write_text(
            "".join(
                json.dumps(row, separators=(",", ":")) + "\n"
                for row in (
                    {
                        "schema_version": "mm_user_stream_journal_v0.1",
                        "event_type": "user_event",
                        "payload": {"orderID": order_id, "status": "live"},
                    },
                    {
                        "schema_version": "mm_user_stream_journal_v0.1",
                        "event_type": "user_event",
                        "payload": {
                            "orderID": order_id,
                            "status": "canceled",
                            "size_matched": "0",
                        },
                    },
                    {
                        "schema_version": "mm_user_stream_journal_v0.1",
                        "event_type": "stream_stopped",
                    },
                )
            ),
            encoding="utf-8",
        )
        result_path.write_text(
            json.dumps(
                {
                    "schema_version": "mm_live_lifecycle_probe_v0.3",
                    "mode": mode,
                    "status": "PASS",
                    "cancellation_mode": mode,
                    "order_id": order_id,
                    "journal_path": str(journal.resolve()),
                    "candidate_plan_sha256": "c" * 64,
                    "submit_boundary_heartbeat_acknowledged": True,
                    "submit_boundary_market_rules_verified": True,
                    "submit_boundary_geography_before_heartbeat_verified": True,
                    "post_sign_order_placement_boundary_verified": True,
                    "terminal_rest_order_verified": True,
                    "terminal_rest_zero_matched_verified": True,
                    "account_trades_rest_verified": True,
                    "scoped_account_trade_count": 0,
                    "post_cancel_quiescence_seconds": 2.0,
                    "terminal_user_event_observed": True,
                    "user_stream_journal_path": str(stream.resolve()),
                    "user_stream_journal_sha256": hashlib.sha256(
                        stream.read_bytes()
                    ).hexdigest(),
                    "cleanup_final_user_stream_journal_sha256": hashlib.sha256(
                        stream.read_bytes()
                    ).hexdigest(),
                    "user_stream_journal_row_count": 3,
                    "user_stream_scoped_order_event_count": 2,
                }
            ),
            encoding="utf-8",
        )
        seal_path = attempt / "seal" / f"{stage_folder}-seal-receipt.json"
        seal_path.parent.mkdir(parents=True, exist_ok=True)
        seal_path.write_text(
            json.dumps(
                {
                    "schema_version": cli.FIXED_SCOPE_SEAL_SCHEMA_VERSION,
                    "status": "PASS",
                    "stage": stage,
                    "production": {"commit": command_args.expected_production_tip},
                    "scope": {
                        "target_date": command_args.target_date,
                        "market_id": "toronto",
                        "market_timezone": "America/Toronto",
                        "condition_id": command_args.condition_id,
                        "token_id": command_args.token_id,
                        "requested_budget_pusd": command_args.budget,
                        "cancellation_mode": mode,
                        "attempt_root": str(attempt.resolve()),
                        "execution_host_profile": "capture_colocated_v1",
                        "execution_host_id": "f" * 64,
                    },
                    "wrapper": {
                        "path": str(wrapper.resolve()),
                        "sha256": hashlib.sha256(wrapper.read_bytes()).hexdigest(),
                    },
                    "launcher": {
                        "path": str(launcher.resolve()),
                        "sha256": hashlib.sha256(launcher.read_bytes()).hexdigest(),
                    },
                }
            ),
            encoding="utf-8",
        )
        command_path = attempt / stage_folder / "command-receipt.json"
        doctor = attempt / stage_folder / "doctor-receipt.json"
        doctor.write_text('{"status":"PASS"}\n', encoding="utf-8")
        geography_precredential = write_geography_receipt(
            attempt / stage_folder / "geography-precredential-receipt.json",
            datetime(2026, 8, 23, 5, 0, tzinfo=timezone.utc),
        )
        geography_presubmit = write_geography_receipt(
            attempt / stage_folder / "geography-presubmit-receipt.json",
            datetime(2026, 8, 23, 5, 0, tzinfo=timezone.utc),
        )
        command_path.write_text(
            json.dumps(
                {
                    "schema_version": cli.RECEIPT_SCHEMA_VERSION,
                    "status": "PASS",
                    "command": "stage1",
                    "target_date": command_args.target_date,
                    "condition_id": command_args.condition_id,
                    "token_id": command_args.token_id,
                    "requested_budget_pusd": command_args.budget,
                    "cancellation_mode": mode,
                    "exchange_mutation_attempted": True,
                    "order_submit_attempted": True,
                    "authenticated_exchange_write_attempted": True,
                    "credential_topology": {
                        "manifest_wallet_address": ADDRESS,
                        "derived_signer_matches_manifest": True,
                        "api_owner_matches_manifest": True,
                        "order_signer_matches_manifest": True,
                        "funder_matches_identity": True,
                    },
                    "cleanup": {"ok": True},
                    "exception_type": None,
                    "paths": {
                        "result": str(result_path.resolve()),
                        "receipt": str(command_path.resolve()),
                        "user_stream_journal": str(stream.resolve()),
                        "lifecycle_journal": str(journal.resolve()),
                    },
                }
            ),
            encoding="utf-8",
        )
        execution_path = attempt / stage_folder / "wrapper-execution-receipt.json"
        execution_path.write_text(
            json.dumps(
                {
                    "schema_version": "international_live_fixed_scope_execution_v0.6",
                    "status": "PASS",
                    "stage": stage,
                    "execution_host_profile": "capture_colocated_v1",
                    "execution_host_id": "f" * 64,
                    "phase": "complete",
                    "production_tip": command_args.expected_production_tip,
                    "target_date": command_args.target_date,
                    "condition_id": command_args.condition_id,
                    "token_id": command_args.token_id,
                    "requested_budget_pusd": command_args.budget,
                    "cancellation_mode": mode,
                    "exception_type": None,
                    "credential_values_read_in_memory": True,
                    "live_mutation_attempted": True,
                    "order_submit_attempted": True,
                    "authenticated_exchange_write_attempted": True,
                    "wrapper": {
                        "path": str(wrapper.resolve()),
                        "sha256": hashlib.sha256(wrapper.read_bytes()).hexdigest(),
                    },
                    "artifacts": {
                        "doctor_receipt_out": {
                            "path": str(doctor.resolve()),
                            "sha256": hashlib.sha256(doctor.read_bytes()).hexdigest(),
                        },
                        "geography_precredential_receipt_out": {
                            "path": str(geography_precredential.resolve()),
                            "sha256": hashlib.sha256(
                                geography_precredential.read_bytes()
                            ).hexdigest(),
                        },
                        "geography_presubmit_receipt_out": {
                            "path": str(geography_presubmit.resolve()),
                            "sha256": hashlib.sha256(
                                geography_presubmit.read_bytes()
                            ).hexdigest(),
                        },
                        "result_out": {
                            "path": str(result_path.resolve()),
                            "sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
                        },
                        "command_receipt_out": {
                            "path": str(command_path.resolve()),
                            "sha256": hashlib.sha256(command_path.read_bytes()).hexdigest(),
                        },
                        "lifecycle_journal_out": {
                            "path": str(journal.resolve()),
                            "sha256": hashlib.sha256(journal.read_bytes()).hexdigest(),
                        },
                        "user_stream_journal_out": {
                            "path": str(stream.resolve()),
                            "sha256": hashlib.sha256(stream.read_bytes()).hexdigest(),
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        lineage_records = {}
        lineage_paths = {
            "session_manifest": attempt / "inputs" / f"{stage}-session-manifest.json",
            "composition_receipt": attempt / "session" / f"{stage}-composition-receipt.json",
            "run_intent": attempt / "session" / f"{stage}-run-intent.json",
        }
        for role, lineage_path in lineage_paths.items():
            lineage_path.parent.mkdir(parents=True, exist_ok=True)
            lineage_path.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
            lineage_records[role] = {
                "path": str(lineage_path.resolve()),
                "sha256": hashlib.sha256(lineage_path.read_bytes()).hexdigest(),
            }
        manifest_sidecar = lineage_paths["session_manifest"].with_suffix(
            lineage_paths["session_manifest"].suffix + ".sha256"
        )
        manifest_sidecar.write_text(
            f"{lineage_records['session_manifest']['sha256']}  "
            f"{lineage_paths['session_manifest'].name}\n",
            encoding="ascii",
        )
        lineage_records["session_manifest"].update(
            {
                "sidecar_path": str(manifest_sidecar.resolve()),
                "sidecar_sha256": hashlib.sha256(
                    manifest_sidecar.read_bytes()
                ).hexdigest(),
            }
        )
        run_path = attempt / "session" / f"{stage}-run-receipt.json"
        run_payload = {
            "schema_version": "international_live_session_run_v0.4",
            "status": "PASS",
            "stage": stage,
            "execution_host_profile": "capture_colocated_v1",
            "execution_host_id": "f" * 64,
            "live_mutation_attempted": True,
            "order_submit_attempted": True,
            "authenticated_exchange_write_attempted": True,
            "credential_topology": {
                "manifest_wallet_address": ADDRESS,
                "derived_signer_matches_manifest": True,
                "api_owner_matches_manifest": True,
                "order_signer_matches_manifest": True,
                "funder_matches_identity": True,
            },
            "credential_values_read_in_memory": True,
            "candidate_sha256": "c" * 64,
            "launcher": {
                "path": str(launcher.resolve()),
                "sha256": hashlib.sha256(launcher.read_bytes()).hexdigest(),
            },
            "wrapper": {
                "path": str(wrapper.resolve()),
                "sha256": hashlib.sha256(wrapper.read_bytes()).hexdigest(),
            },
            "child_execution": {
                "validation": "PASS",
                "status": "PASS",
                "phase": "complete",
                "path": str(execution_path.resolve()),
                "sha256": hashlib.sha256(execution_path.read_bytes()).hexdigest(),
            },
            "seal_receipt": {
                "path": str(seal_path.resolve()),
                "sha256": hashlib.sha256(seal_path.read_bytes()).hexdigest(),
            },
            **lineage_records,
        }
        run_path.write_text(json.dumps(run_payload), encoding="utf-8")
        run_path.with_suffix(run_path.suffix + ".sha256").write_text(
            f"{hashlib.sha256(run_path.read_bytes()).hexdigest()}  {run_path.name}\n",
            encoding="ascii",
        )
        setattr(command_args, f"{prefix}_seal_receipt", str(seal_path))
        setattr(command_args, f"{prefix}_command_receipt", str(command_path))
        setattr(command_args, f"{prefix}_execution_receipt", str(execution_path))
        setattr(command_args, f"{prefix}_run_receipt", str(run_path))

    add_lineage("cancel_all", cancel_result)
    add_lineage("dead_man", dead_result)
    cancel_command = Path(command_args.cancel_all_command_receipt)
    original_command = cancel_command.read_bytes()
    cancel_command.write_bytes(original_command + b"\n")
    with pytest.raises(RuntimeError, match="lineage failed"):
        cli._validate_stage1_bundle_lineage(
            command_args, "cancel_all", cancel_result
        )
    cancel_command.write_bytes(original_command)
    original_dead_execution = command_args.dead_man_execution_receipt
    command_args.dead_man_execution_receipt = str(tmp_path / "missing-execution.json")
    with pytest.raises(RuntimeError, match="cannot read required JSON"):
        cli._validate_stage1_bundle_lineage(command_args, "dead_man", dead_result)
    command_args.dead_man_execution_receipt = original_dead_execution
    cancel_run = Path(command_args.cancel_all_run_receipt)
    original_run = cancel_run.read_bytes()
    original_run_sidecar = cancel_run.with_suffix(
        cancel_run.suffix + ".sha256"
    ).read_bytes()
    partial_run = json.loads(original_run)
    partial_run["child_execution"]["status"] = "UNKNOWN"
    cancel_run.write_text(json.dumps(partial_run), encoding="utf-8")
    cancel_run.with_suffix(cancel_run.suffix + ".sha256").write_text(
        f"{hashlib.sha256(cancel_run.read_bytes()).hexdigest()}  {cancel_run.name}\n",
        encoding="ascii",
    )
    with pytest.raises(RuntimeError, match="lineage failed"):
        cli._validate_stage1_bundle_lineage(
            command_args, "cancel_all", cancel_result
        )
    cancel_run.write_bytes(original_run)
    cancel_run.with_suffix(cancel_run.suffix + ".sha256").write_bytes(
        original_run_sidecar
    )
    seen = {}

    def builder(gate, cancel_all, dead_man):
        seen.update(gate=gate, cancel_all=cancel_all, dead_man=dead_man)
        return {
            "schema_version": "mm_stage1_lifecycle_bundle_v0.3",
            "status": "PASS",
        }

    receipt = cli.run_bundle(
        command_args,
        bootstrap_loader=lambda *_args, **_kwargs: {
            "ok": True,
            "requested_budget_usdc": 10.0,
            "pilot_wallet_max_funding_usdc": 100.0,
        },
        bundle_builder=builder,
    )

    assert receipt["status"] == "PASS"
    assert set(receipt["stage1_lineage"]) == {"cancel_all", "dead_man"}
    assert seen["cancel_all"]["mode"] == "cancel_all"
    assert seen["dead_man"]["mode"] == "dead_man"
    assert json.loads(open(command_args.bundle_out, encoding="utf-8").read())["status"] == "PASS"
    saved_receipt = json.loads(open(command_args.receipt_out, encoding="utf-8").read())
    assert saved_receipt["cleanup"]["reason"] == "offline_command_no_exchange_state"


def test_wrong_confirmation_stops_before_credentials_or_mutation(tmp_path):
    command_args = args(tmp_path, "stage1")
    command_args.confirmation = "yes"
    called = False

    def build(*_args, **_kwargs):
        nonlocal called
        called = True
        return context(tmp_path)

    with pytest.raises(RuntimeError, match="exact lifecycle confirmation"):
        cli.run_stage1(command_args, context_builder=build)

    assert called is False
    assert not (tmp_path / "stage1-receipt.json").exists()
    assert not (tmp_path / "stage1-result.json").exists()


def test_stage1_requires_sealed_pre_submit_attestor_before_credentials(tmp_path):
    command_args = args(tmp_path, "stage1")
    command_args.pre_submit_attestor = None
    called = False

    def build(*_args, **_kwargs):
        nonlocal called
        called = True
        return context(tmp_path)

    with pytest.raises(RuntimeError, match="sealed pre-submit attestor"):
        cli.run_stage1(command_args, context_builder=build)

    assert called is False
    assert not Path(command_args.receipt_out).exists()
    assert not Path(command_args.result_out).exists()


def test_output_directories_are_proved_writable_before_context_construction(tmp_path):
    command_args = args(tmp_path, "stage1")
    output_root = tmp_path / "new" / "protected-pilot"
    command_args.result_out = str(output_root / "result.json")
    command_args.receipt_out = str(output_root / "receipt.json")
    command_args.user_stream_journal = str(output_root / "stream.jsonl")
    command_args.lifecycle_journal = str(output_root / "lifecycle.jsonl")
    called = False

    def build(*_args, **_kwargs):
        nonlocal called
        called = True
        raise RuntimeError("stop after storage preflight")

    with pytest.raises(RuntimeError, match="stop after storage preflight"):
        cli.run_stage1(
            command_args,
            context_builder=build,
            bootstrap_loader=lambda *_args, **_kwargs: {"ok": True},
        )

    assert called is True
    assert output_root.is_dir()
    assert list(output_root.iterdir()) == [output_root / "receipt.json"]
    receipt = json.loads((output_root / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "FAIL"


def test_context_wires_only_in_memory_secrets_and_exact_readers(tmp_path):
    class Credentials:
        api_key = "key-secret"
        api_secret = "api-secret"
        api_passphrase = "pass-secret"
        private_key = "private-secret"
        funder = ADDRESS

    captured = {}

    class StreamFactory(FakeStream):
        def __init__(self, **kwargs):
            super().__init__(kwargs["journal_path"])
            captured["stream"] = kwargs

    class AdapterFactory:
        def __init__(self, client, **kwargs):
            captured["adapter_client"] = client
            captured["adapter"] = kwargs

        def diagnostics(self):
            return {"supports_trading": True}

    def position_fetcher(maker, condition):
        captured["position_scope"] = (maker, condition)
        return {"rows": []}

    client = SimpleNamespace(signer="0x" + "c" * 40)

    def heartbeat_sender_factory(**kwargs):
        captured["heartbeat_sender"] = kwargs
        return "heartbeat-sender"

    def market_rule_fetcher(token):
        captured["market_rule_token"] = token
        return {"token_id": token}

    result = cli.build_live_pilot_context(
        {"identity": "public", "funder_address": ADDRESS},
        token_id=TOKEN_ID,
        condition_id=CONDITION_ID,
        user_stream_journal=tmp_path / "stream.jsonl",
        expected_wallet_address=client.signer,
        credential_loader=lambda _env: Credentials(),
        client_builder=lambda credentials, identity, **_kwargs: client,
        user_stream_factory=StreamFactory,
        adapter_factory=AdapterFactory,
        position_fetcher=position_fetcher,
        heartbeat_sender_factory=heartbeat_sender_factory,
        market_rule_fetcher=market_rule_fetcher,
    )

    assert repr(result) == (
        "LivePilotContext(credentials=<redacted>, client=<redacted>, stream=<redacted>)"
    )
    assert captured["adapter"]["authoritative_readers_verified"] is True
    assert captured["adapter"]["max_order_notional"] == 10.0
    assert captured["adapter"]["heartbeat_sender"] == "heartbeat-sender"
    assert captured["heartbeat_sender"]["signer_address"] == client.signer
    assert captured["heartbeat_sender"]["api_secret"] == "api-secret"
    assert captured["stream"]["journal_path"] == tmp_path / "stream.jsonl"
    captured["adapter"]["position_reader"]()
    assert captured["position_scope"] == (ADDRESS, CONDITION_ID)
    captured["adapter"]["market_rule_reader"]()
    assert captured["market_rule_token"] == TOKEN_ID


def test_context_closes_the_unified_client_when_wiring_fails(tmp_path):
    class Credentials:
        api_key = "key-secret"
        api_secret = "api-secret"
        api_passphrase = "pass-secret"
        funder = ADDRESS

    class Client(FakeClient):
        signer = "0x" + "c" * 40

    class Adapter:
        def __init__(self, _client, **_kwargs):
            pass

        def diagnostics(self):
            return {"supports_trading": False}

    client = Client()
    with pytest.raises(RuntimeError, match="authoritative reader boundary"):
        cli.build_live_pilot_context(
            {"identity": "public", "funder_address": ADDRESS},
            token_id=TOKEN_ID,
            condition_id=CONDITION_ID,
            user_stream_journal=tmp_path / "failed-stream.jsonl",
            expected_wallet_address=client.signer,
            credential_loader=lambda _env: Credentials(),
            client_builder=lambda credentials, identity, **_kwargs: client,
            user_stream_factory=lambda **kwargs: FakeStream(kwargs["journal_path"]),
            adapter_factory=Adapter,
            heartbeat_sender_factory=lambda **_kwargs: object(),
            market_rule_fetcher=lambda token: {"token_id": token},
        )

    assert client.closed is True


@pytest.mark.parametrize("command", ["stage0", "stage1"])
def test_parser_does_not_expose_exchange_mutation_commands(command):
    with pytest.raises(SystemExit) as exc:
        cli.build_parser().parse_args([command])

    assert exc.value.code == 2


def test_main_reports_only_exception_type_not_raw_message(monkeypatch, capsys, tmp_path):
    identity = tmp_path / "identity.json"
    identity.write_text("{}", encoding="utf-8")
    argv = [
        "doctor",
        "--identity", str(identity),
        "--target-date", "2026-08-14",
        "--condition-id", CONDITION_ID,
        "--token-id", TOKEN_ID,
        "--budget", "100",
        "--receipt-out", str(tmp_path / "doctor-receipt.json"),
        "--confirmation", cli.DOCTOR_CONFIRMATION,
    ]
    monkeypatch.setattr(
        cli,
        "run_doctor",
        lambda _args: (_ for _ in ()).throw(RuntimeError("RAW-SECRET-MESSAGE")),
    )

    assert cli.main(argv) == 1
    stderr = capsys.readouterr().err
    assert "RuntimeError" in stderr
    assert "RAW-SECRET-MESSAGE" not in stderr
