from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json

import pytest

from weather.market.live_taker_state import (
    AccountReconciliationEvidence,
    AuthorityState,
    CampaignBusyError,
    CampaignLock,
    CanaryStateMachine,
    DuplicateIntentError,
    GENESIS_HASH,
    HaltedRecoveryScope,
    HashChainJournal,
    MAX_JOURNAL_RECORD_BYTES,
    MAX_STATUS_BYTES,
    ReviewedRecoveryEvidence,
    SecretMaterialError,
    StateTransitionError,
    make_idempotency_key,
    status_content_sha256,
    validate_status_snapshot,
    verify_hash_chain,
    verify_status_snapshot,
    write_status_snapshot,
)


FIXED_TIME = datetime(2026, 7, 21, 12, 30, tzinfo=timezone.utc)
ACCOUNT_DIGEST = "acct_" + "a" * 24
ACCOUNT_SHA256 = "a" * 64
MANIFEST_SHA256 = "f" * 64
ACTIVATION_SCOPE_SHA256 = "1" * 64


def _halted_scope(**changes) -> HaltedRecoveryScope:
    values = {
        "platform": "polymarket_global",
        "account_id_sha256": ACCOUNT_SHA256,
        "release_id": "release-1",
        "manifest_sha256": MANIFEST_SHA256,
        "activation_scope_sha256": ACTIVATION_SCOPE_SHA256,
        "halted_ledger_high_water": 9,
    }
    values.update(changes)
    return HaltedRecoveryScope(**values)


def _reconciliation(**changes) -> AccountReconciliationEvidence:
    values = {
        "reconciliation_id": "reconcile-halt-9",
        "platform": "polymarket_global",
        "account_id_sha256": ACCOUNT_SHA256,
        "release_id": "release-1",
        "manifest_sha256": MANIFEST_SHA256,
        "activation_scope_sha256": ACTIVATION_SCOPE_SHA256,
        "observed_at_utc": FIXED_TIME + timedelta(seconds=30),
        "sequence": 10,
        "status": "PASS",
        "open_order_count": 0,
        "unknown_order_count": 0,
        "position_reconciliation_status": "PASS",
        "cash_reconciliation_status": "PASS",
        "account_snapshot_sha256": "b" * 64,
        "open_orders_snapshot_sha256": "c" * 64,
        "positions_snapshot_sha256": "d" * 64,
        "cash_ledger_sha256": "e" * 64,
    }
    values.update(changes)
    return AccountReconciliationEvidence(**values)


def _recovery(**changes) -> ReviewedRecoveryEvidence:
    values = {
        "recovery_id": "recovery-review-9",
        "reviewed_by": "risk-operator",
        "reviewed_at_utc": FIXED_TIME + timedelta(minutes=1),
        "halt_sequence": 9,
        "reconciliation": _reconciliation(),
    }
    values.update(changes)
    return ReviewedRecoveryEvidence(**values)


def test_state_machine_enforces_restart_through_reconcile_only():
    machine = CanaryStateMachine()
    machine, preflight = machine.transition(
        AuthorityState.PREFLIGHT,
        reason_code="READ_ONLY_PREFLIGHT_STARTED",
        recorded_at_utc=FIXED_TIME,
    )
    machine, _ = machine.transition(
        AuthorityState.ARMED,
        reason_code="EXACT_ACTIVATION_VERIFIED",
        recorded_at_utc=FIXED_TIME,
    )
    machine, reconcile = machine.transition(
        AuthorityState.RECONCILE_ONLY,
        reason_code="WORKER_START_REQUIRES_RECONCILIATION",
        recorded_at_utc=FIXED_TIME,
    )

    assert preflight.as_record()["network_write_phase"] is False
    assert reconcile.previous_state is AuthorityState.ARMED
    assert machine.state is AuthorityState.RECONCILE_ONLY
    assert machine.sequence == 3
    assert machine.in_submission_phase is False
    with pytest.raises(StateTransitionError):
        machine.transition(
            AuthorityState.SUBMITTING,
            reason_code="SKIP_RECONCILIATION",
            recorded_at_utc=FIXED_TIME,
        )


def test_submitting_is_only_a_phase_marker_and_not_an_authority_claim():
    machine = CanaryStateMachine(AuthorityState.SCANNING, sequence=8)
    machine, event = machine.transition(
        AuthorityState.SUBMITTING,
        reason_code="FINAL_ORDER_GATE_REVALIDATED",
        recorded_at_utc=FIXED_TIME,
    )

    assert machine.in_submission_phase is True
    assert event.as_record()["network_write_phase"] is True
    assert "submission_authorized" not in event.as_record()
    machine, halted = machine.transition(
        AuthorityState.HALTED,
        reason_code="SUBMISSION_OUTCOME_UNKNOWN",
        recorded_at_utc=FIXED_TIME,
        halted_recovery_scope=_halted_scope(),
    )
    assert machine.in_submission_phase is False
    assert halted.as_record()["halted_recovery_scope"]["release_id"] == "release-1"
    assert len(
        halted.as_record()["halted_recovery_scope"][
            "halted_recovery_scope_sha256"
        ]
    ) == 64


def test_entering_or_reconstructing_halted_requires_persisted_scope():
    machine = CanaryStateMachine(AuthorityState.SCANNING, sequence=8)
    with pytest.raises(StateTransitionError, match="persisted recovery scope"):
        machine.transition(
            AuthorityState.HALTED,
            reason_code="RISK_HALT",
            recorded_at_utc=FIXED_TIME,
        )
    with pytest.raises(ValueError, match="exact recovery scope"):
        CanaryStateMachine(
            AuthorityState.HALTED,
            sequence=9,
            last_transition_at_utc=FIXED_TIME,
        )


def test_halted_recovery_fails_closed_without_structured_review_evidence():
    machine = CanaryStateMachine(
        AuthorityState.HALTED,
        sequence=9,
        last_transition_at_utc=FIXED_TIME,
        halted_recovery_scope=_halted_scope(),
    )

    with pytest.raises(StateTransitionError, match="structured reviewed"):
        machine.transition(
            AuthorityState.RECONCILE_ONLY,
            reason_code="OPERATOR_SAID_RESUME",
            recorded_at_utc=FIXED_TIME + timedelta(minutes=2),
        )


def test_halted_recovery_requires_exact_reviewed_reconciliation_evidence():
    machine = CanaryStateMachine(
        AuthorityState.HALTED,
        sequence=9,
        last_transition_at_utc=FIXED_TIME,
        halted_recovery_scope=_halted_scope(),
    )
    evidence = _recovery()

    recovered, event = machine.transition(
        AuthorityState.RECONCILE_ONLY,
        reason_code="REVIEWED_RECOVERY_TO_RECONCILE_ONLY",
        recovery_evidence=evidence,
        recorded_at_utc=FIXED_TIME + timedelta(minutes=2),
    )

    record = event.as_record()
    assert recovered.state is AuthorityState.RECONCILE_ONLY
    assert record["network_write_phase"] is False
    assert record["recovery_evidence"]["halt_sequence"] == 9
    reconciliation = record["recovery_evidence"]["reconciliation"]
    assert reconciliation["status"] == "PASS"
    assert reconciliation["open_order_count"] == 0
    assert len(reconciliation["reconciliation_evidence_sha256"]) == 64
    assert len(record["recovery_evidence"]["recovery_evidence_sha256"]) == 64


def test_reviewed_recovery_transition_round_trips_through_hash_chain(tmp_path):
    machine = CanaryStateMachine(
        AuthorityState.HALTED,
        sequence=9,
        last_transition_at_utc=FIXED_TIME,
        halted_recovery_scope=_halted_scope(),
    )
    _recovered, event = machine.transition(
        AuthorityState.RECONCILE_ONLY,
        reason_code="REVIEWED_RECOVERY_TO_RECONCILE_ONLY",
        recovery_evidence=_recovery(),
        recorded_at_utc=FIXED_TIME + timedelta(minutes=2),
    )
    path = tmp_path / "recovery_events.jsonl"

    HashChainJournal(path).append(
        "authority_state_transition",
        event.as_record(),
        recorded_at_utc=FIXED_TIME + timedelta(minutes=2),
    )

    verification = verify_hash_chain(path)
    payload = json.loads(path.read_text(encoding="utf-8"))["payload"]
    assert verification.valid is True
    assert payload["schema_version"] == "capital_canary_journal_event_v0.2"
    assert payload["recovery_evidence"]["reconciliation"]["open_order_count"] == 0


def test_halted_recovery_rejects_misbound_review_evidence():
    machine = CanaryStateMachine(
        AuthorityState.HALTED,
        sequence=9,
        last_transition_at_utc=FIXED_TIME,
        halted_recovery_scope=_halted_scope(),
    )
    stale = _recovery(
        recovery_id="recovery-review-8",
        reviewed_at_utc=FIXED_TIME - timedelta(seconds=1),
        halt_sequence=8,
    )

    with pytest.raises(StateTransitionError, match="current halted sequence"):
        machine.transition(
            AuthorityState.RECONCILE_ONLY,
            reason_code="REVIEWED_RECOVERY_TO_RECONCILE_ONLY",
            recovery_evidence=stale,
            recorded_at_utc=FIXED_TIME + timedelta(minutes=2),
        )


def test_halted_recovery_rejects_review_from_before_the_halt():
    machine = CanaryStateMachine(
        AuthorityState.HALTED,
        sequence=9,
        last_transition_at_utc=FIXED_TIME,
        halted_recovery_scope=_halted_scope(),
    )
    stale = _recovery(reviewed_at_utc=FIXED_TIME - timedelta(seconds=1))

    with pytest.raises(StateTransitionError, match="follow the halt"):
        machine.transition(
            AuthorityState.RECONCILE_ONLY,
            reason_code="REVIEWED_RECOVERY_TO_RECONCILE_ONLY",
            recovery_evidence=stale,
            recorded_at_utc=FIXED_TIME + timedelta(minutes=2),
        )


@pytest.mark.parametrize(
    "reconciliation_changes",
    [
        {"platform": "polymarket_us"},
        {"account_id_sha256": "2" * 64},
        {"release_id": "release-2"},
        {"manifest_sha256": "3" * 64},
        {"activation_scope_sha256": "4" * 64},
    ],
)
def test_halted_recovery_rejects_wrong_identity_scope(reconciliation_changes):
    machine = CanaryStateMachine(
        AuthorityState.HALTED,
        sequence=9,
        last_transition_at_utc=FIXED_TIME,
        halted_recovery_scope=_halted_scope(),
    )
    evidence = _recovery(reconciliation=_reconciliation(**reconciliation_changes))

    with pytest.raises(StateTransitionError, match="halted recovery scope"):
        machine.transition(
            AuthorityState.RECONCILE_ONLY,
            reason_code="REVIEWED_RECOVERY_TO_RECONCILE_ONLY",
            recovery_evidence=evidence,
            recorded_at_utc=FIXED_TIME + timedelta(minutes=2),
        )


def test_halted_recovery_requires_newer_reconciliation_sequence():
    machine = CanaryStateMachine(
        AuthorityState.HALTED,
        sequence=9,
        last_transition_at_utc=FIXED_TIME,
        halted_recovery_scope=_halted_scope(halted_ledger_high_water=10),
    )
    evidence = _recovery(reconciliation=_reconciliation(sequence=10))

    with pytest.raises(StateTransitionError, match="not newer"):
        machine.transition(
            AuthorityState.RECONCILE_ONLY,
            reason_code="REVIEWED_RECOVERY_TO_RECONCILE_ONLY",
            recovery_evidence=evidence,
            recorded_at_utc=FIXED_TIME + timedelta(minutes=2),
        )


@pytest.mark.parametrize(
    ("factory", "changes", "message"),
    [
        (_reconciliation, {"reconciliation_id": None}, "reconciliation_id"),
        (_reconciliation, {"release_id": None}, "release_id"),
        (_reconciliation, {"platform": None}, "supported exact platform"),
        (_reconciliation, {"platform": "other"}, "supported exact platform"),
        (_recovery, {"recovery_id": None}, "recovery_id"),
        (_recovery, {"reviewed_by": None}, "reviewed_by"),
    ],
)
def test_recovery_identifiers_require_exact_bounded_strings(factory, changes, message):
    with pytest.raises(ValueError, match=message):
        factory(**changes)


def test_reviewed_recovery_evidence_requires_passing_reconciliation():
    with pytest.raises(ValueError, match="must be PASS"):
        _reconciliation(status="BLOCK")


def test_idempotency_key_is_deterministic_and_decimal_normalized():
    common = {
        "platform": "Polymarket",
        "account_identity_redacted": ACCOUNT_DIGEST,
        "event_id": "event-2026-07-22",
        "token_id": "123456789",
        "side": "BUY_YES",
        "quantity": Decimal("0.5000"),
        "release_hash": "b" * 64,
        "snapshot_hash": "c" * 64,
        "policy_hash": "d" * 64,
        "sequence": 9,
    }

    first = make_idempotency_key(limit_price=Decimal("0.9000"), **common)
    second = make_idempotency_key(limit_price="0.9", **common)
    changed = make_idempotency_key(
        limit_price="0.9",
        **{**common, "sequence": 10},
    )
    decision_bound = make_idempotency_key(
        limit_price="0.9",
        risk_decision_hash="e" * 64,
        **common,
    )
    changed_decision = make_idempotency_key(
        limit_price="0.9",
        risk_decision_hash="f" * 64,
        **common,
    )

    assert first == second
    assert first.startswith("capital-canary:")
    assert len(first.removeprefix("capital-canary:")) == 64
    assert changed != first
    assert decision_bound != first
    assert changed_decision != decision_bound


def test_idempotency_key_rejects_raw_account_identity():
    with pytest.raises(ValueError, match="digest label"):
        make_idempotency_key(
            platform="polymarket",
            account_identity_redacted="0x" + "a" * 40,
            event_id="event",
            token_id="token",
            side="BUY",
            limit_price="0.90",
            quantity="0.5",
            release_hash="b" * 64,
            snapshot_hash="c" * 64,
            policy_hash="d" * 64,
            sequence=1,
        )


def test_idempotency_key_requires_exact_sha256_lineage():
    with pytest.raises(ValueError, match="release_hash"):
        make_idempotency_key(
            platform="polymarket",
            account_identity_redacted=ACCOUNT_DIGEST,
            event_id="event",
            token_id="token",
            side="BUY",
            limit_price="0.90",
            quantity="0.5",
            release_hash="not-a-hash",
            snapshot_hash="c" * 64,
            policy_hash="d" * 64,
            sequence=1,
        )


def test_hash_chain_journal_is_fsynced_verifiable_and_detects_tampering(tmp_path):
    path = tmp_path / "order_intents.jsonl"
    journal = HashChainJournal(path)

    first = journal.append(
        "intent_reserved",
        {"idempotency_key": "capital-canary:" + "a" * 64, "risk_usdc": Decimal("0.50")},
        recorded_at_utc=FIXED_TIME,
    )
    second = journal.append(
        "intent_reconciled",
        {"result": "NO_FILL", "risk_released_usdc": Decimal("0.50")},
        recorded_at_utc=FIXED_TIME,
    )

    verified = verify_hash_chain(path)
    assert verified.valid is True
    assert verified.record_count == 2
    assert first["previous_hash"] == GENESIS_HASH
    assert second["previous_hash"] == first["record_hash"]
    assert verified.last_hash == second["record_hash"]

    rows = path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(rows[0])
    tampered["payload"]["risk_usdc"] = "0.51"
    rows[0] = json.dumps(tampered, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    failed = verify_hash_chain(path)
    assert failed.valid is False
    assert failed.error_code == "RECORD_HASH_MISMATCH"


def test_campaign_lock_allows_only_one_lifetime_worker(tmp_path):
    path = tmp_path / "campaign.lock"
    first = CampaignLock(path)
    second = CampaignLock(path)

    first.acquire(acquired_at_utc=FIXED_TIME)
    assert first.owned is True
    with pytest.raises(CampaignBusyError, match="requires review"):
        second.acquire(acquired_at_utc=FIXED_TIME)

    first.release()
    with second:
        assert second.owned is True
        assert path.is_file()
    assert not path.exists()


def test_intent_reservation_is_durably_unique(tmp_path):
    path = tmp_path / "order_intents.jsonl"
    journal = HashChainJournal(path)
    payload = {
        "idempotency_key": "capital-canary:" + "a" * 64,
        "risk_usdc": Decimal("0.50"),
    }
    journal.append("intent_reserved", payload, recorded_at_utc=FIXED_TIME)

    with pytest.raises(DuplicateIntentError, match="durable reservation"):
        journal.append("intent_reserved", payload, recorded_at_utc=FIXED_TIME)

    assert verify_hash_chain(path).record_count == 1


def test_journal_and_status_reads_are_bounded(tmp_path):
    journal_path = tmp_path / "oversized.jsonl"
    journal_path.write_bytes(b"x" * (MAX_JOURNAL_RECORD_BYTES + 1) + b"\n")
    verification = verify_hash_chain(journal_path)

    assert verification.valid is False
    assert verification.error_code == "RECORD_OVERSIZED"

    status_path = tmp_path / "oversized-status.json"
    status_path.write_bytes(b"{" + b" " * MAX_STATUS_BYTES + b"}")

    snapshot = validate_status_snapshot(status_path)
    assert snapshot.valid is False
    assert snapshot.error_code == "MALFORMED"


def test_journal_rejects_secret_without_echoing_or_writing_it(tmp_path):
    path = tmp_path / "risk_events.jsonl"
    secret = "test-private-key-material-that-must-not-leak"

    with pytest.raises(SecretMaterialError) as caught:
        HashChainJournal(path).append(
            "credential_fault",
            {"polymarket_private_key": secret},
            recorded_at_utc=FIXED_TIME,
        )

    assert secret not in str(caught.value)
    assert not path.exists()


def test_status_snapshot_is_atomic_self_hashed_and_secret_free(tmp_path):
    path = tmp_path / "status.json"
    snapshot = write_status_snapshot(
        path,
        {
            "state": "LOCKED",
            "capital_ceiling_usdc": Decimal("75.00"),
            "reconciled_equity_usdc": None,
            "heartbeat_age_seconds": 1.25,
            "credential_access_enabled": False,
            "credential_reference_status": "NOT_READ",
            "blockers": ["CAPITAL_READINESS_NOT_PASSED"],
        },
        sequence=2,
        ledger_sequence=2,
        ledger_hash="e" * 64,
        generated_at_utc=FIXED_TIME,
    )

    assert snapshot["generated_at_utc"] == "2026-07-21T12:30:00Z"
    assert snapshot["capital_ceiling_usdc"] == "75"
    assert snapshot["reconciled_equity_usdc"] is None
    assert snapshot["heartbeat_age_seconds"] == 1.25
    assert snapshot["status_sha256"] == status_content_sha256(snapshot)
    assert verify_status_snapshot(path) is True
    assert not list(tmp_path.glob("*.tmp"))

    on_disk = json.loads(path.read_text(encoding="utf-8"))
    on_disk["state"] = "LIVE"
    path.write_text(json.dumps(on_disk), encoding="utf-8")
    verification = validate_status_snapshot(path)
    assert verification.valid is False
    assert verification.error_code == "STATUS_HASH_MISMATCH"


def test_status_high_water_can_be_cross_verified_against_journal(tmp_path):
    journal_path = tmp_path / "events.jsonl"
    record = HashChainJournal(journal_path).append(
        "risk_checked",
        {"result": "PASS"},
        recorded_at_utc=FIXED_TIME,
    )
    status_path = tmp_path / "status.json"
    write_status_snapshot(
        status_path,
        {"state": "SCANNING"},
        sequence=1,
        ledger_sequence=1,
        ledger_hash=record["record_hash"],
        generated_at_utc=FIXED_TIME,
    )

    assert verify_status_snapshot(status_path, journal_path=journal_path) is True

    other_journal = tmp_path / "other.jsonl"
    other_record = HashChainJournal(other_journal).append(
        "risk_checked",
        {"result": "PASS", "other": True},
        recorded_at_utc=FIXED_TIME,
    )
    assert other_record["record_hash"] != record["record_hash"]
    verification = validate_status_snapshot(
        status_path,
        journal_path=other_journal,
    )
    assert verification.valid is False
    assert verification.error_code == "LEDGER_HIGH_WATER_MISMATCH"


def test_status_writer_rejects_secret_and_reserved_fields(tmp_path):
    path = tmp_path / "status.json"
    secret = "do-not-print-this-secret"

    with pytest.raises(SecretMaterialError) as caught:
        write_status_snapshot(
            path,
            {"api_secret": secret},
            sequence=0,
            ledger_hash=GENESIS_HASH,
            generated_at_utc=FIXED_TIME,
        )
    assert secret not in str(caught.value)
    assert not path.exists()

    with pytest.raises(ValueError, match="reserved"):
        write_status_snapshot(
            path,
            {"sequence": 999},
            sequence=0,
            ledger_hash=GENESIS_HASH,
            generated_at_utc=FIXED_TIME,
        )

    with pytest.raises(TypeError, match="cannot be floats"):
        write_status_snapshot(
            path,
            {"cash_available_usdc": 74.5},
            sequence=0,
            ledger_hash=GENESIS_HASH,
            generated_at_utc=FIXED_TIME,
        )
