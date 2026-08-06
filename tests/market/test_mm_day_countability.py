import json
import csv
import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from weather.market.mm_day_countability import (
    build_day_countability,
    build_execution_tape_inventory,
    confirmation_reservation_gate,
)
from weather.market.market_microstructure_capture import payload_sha1
from weather.market.mm_execution_capture import (
    BOOK_ALIGNMENT_SEQUENCE_STATUS,
    BOUND_SESSION_SCHEMA_VERSION,
    CONNECTION_SEQUENCE_SCOPE,
    EXECUTION_ROW_SCHEMA_VERSION,
    EXECUTION_TAPE_COLUMNS,
    RAW_EXECUTION_SCHEMA_VERSION,
    _asset_set_sha256,
    _receipt_binding_sha256,
)
from weather.market.mm_paper_constants import (
    DEFAULT_CONFIG,
    EXECUTION_CANONICAL_TAPE_FILENAME,
    EXECUTION_RAW_TAPE_FILENAME,
    EXECUTION_SESSION_FILENAME,
)
from weather.market.mm_paper_scoring import simulate_conservative_fills
from weather.market.mm_reward_q_share import build_sampled_reward_q_share


UTC = timezone.utc


def _clear_reservation_gate(target_date="2026-08-04"):
    return {
        "status": "PASS",
        "state": "ARMED_UNDATED",
        "target_date": target_date,
        "blockers": [],
    }


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_bound_receipt(
    folder,
    *,
    event_slug,
    assets,
    start,
    end,
    execution_count,
    message_count,
    session_id="session-1",
):
    raw_path = folder / EXECUTION_RAW_TAPE_FILENAME
    canonical_path = folder / EXECUTION_CANONICAL_TAPE_FILENAME
    raw_bytes = raw_path.read_bytes() if raw_path.exists() else b""
    canonical_bytes = canonical_path.read_bytes() if canonical_path.exists() else b""
    assets = sorted(assets)
    receipt = {
        "schema_version": BOUND_SESSION_SCHEMA_VERSION,
        "session_id": session_id,
        "coverage_start_utc": start.isoformat(),
        "coverage_end_utc": end.isoformat(),
        "status": "COMPLETE",
        "reason": "duration_complete",
        "continuous_coverage": True,
        "retention_mode": "executions-only",
        "lock_scope": "execution-tape",
        "host_policy_mode": "pause-training-window",
        "message_count": message_count,
        "market_data_message_count": message_count,
        "inbound_liveness_timeout_seconds": 30.0,
        "local_connection_message_sequence_start": 1 if message_count else 0,
        "local_connection_message_sequence_end": message_count,
        "connection_sequence_scope": CONNECTION_SEQUENCE_SCOPE,
        "event_slug": event_slug,
        "market_id": "testville",
        "target_date": "2026-08-04",
        "subscribed_asset_ids": assets,
        "subscribed_asset_count": len(assets),
        "subscribed_asset_set_sha256": _asset_set_sha256(assets),
        "observed_subscribed_asset_ids": assets,
        "observed_subscribed_asset_count": len(assets),
        "observed_subscribed_asset_set_sha256": _asset_set_sha256(assets),
        "execution_count": execution_count,
        "raw_tape_filename": EXECUTION_RAW_TAPE_FILENAME,
        "raw_tape_prefix_size_bytes": len(raw_bytes),
        "raw_tape_prefix_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "canonical_tape_filename": EXECUTION_CANONICAL_TAPE_FILENAME,
        "canonical_tape_prefix_size_bytes": len(canonical_bytes),
        "canonical_tape_prefix_sha256": hashlib.sha256(canonical_bytes).hexdigest(),
    }
    receipt["receipt_binding_sha256"] = _receipt_binding_sha256(receipt)
    _write_jsonl(folder / EXECUTION_SESSION_FILENAME, [receipt])
    return receipt


def _rebind_existing_receipt(folder):
    receipt_path = folder / EXECUTION_SESSION_FILENAME
    receipt = json.loads(receipt_path.read_text(encoding="utf-8").strip())
    for prefix, filename in (
        ("raw", EXECUTION_RAW_TAPE_FILENAME),
        ("canonical", EXECUTION_CANONICAL_TAPE_FILENAME),
    ):
        payload = (folder / filename).read_bytes()
        receipt[f"{prefix}_tape_prefix_size_bytes"] = len(payload)
        receipt[f"{prefix}_tape_prefix_sha256"] = hashlib.sha256(payload).hexdigest()
    receipt["receipt_binding_sha256"] = _receipt_binding_sha256(receipt)
    _write_jsonl(receipt_path, [receipt])


def _constructive_inputs(root):
    event_slug = "highest-temperature-in-testville-on-august-4-2026"
    folder = root / event_slug
    quote_time = datetime(2026, 8, 4, 14, 0, tzinfo=UTC)
    leg = {
        "leg_id": "leg-1",
        "quote_id": "quote-1",
        "run_id": "run-1",
        "run_folder": "retained/run-1",
        "run_mode": "paper-live-forward",
        "policy_hash": "locked-policy",
        "target_date": "2026-08-04",
        "event_slug": event_slug,
        "market_id": "testville",
        "range_label": "80-81 F",
        "bin_kind": "eq",
        "bin_value": 80,
        "bin_value_hi": 81,
        "clob_token_id": "yes-1",
        "side": "YES_BID",
        "direction": 1.0,
        "quote_price": 0.50,
        "quote_size": 10.0,
        "quote_time": quote_time,
        "quote_expires_at": quote_time + timedelta(seconds=60),
        "tick_size": 0.01,
        "min_order_size": 1.0,
        "market_mid": 0.51,
        "fair_probability": 0.55,
        "edge": 0.04,
        "regime": "harvest",
        "source_fresh": True,
        "book_imbalance_bucket": "balanced",
        "band_distance_bucket": "near",
        "reward_estimate_usdc": 0.0,
    }
    quote = {
        "target_date": "2026-08-04",
        "event_slug": event_slug,
        "market_id": "testville",
        "clob_token_id": "yes-1",
        "generated_at_utc": quote_time.isoformat(),
    }
    _write_jsonl(folder / "order_books.jsonl", [{
        "capture_id": "book-1",
        "captured_at_utc": (quote_time - timedelta(seconds=10)).isoformat(),
        "event_slug": event_slug,
        "market_id": "testville",
        "clob_token_id": "yes-1",
        "book": {
            "asset_id": "yes-1",
            "tick_size": "0.01",
            "min_order_size": "1",
            "bids": [{"price": "0.49", "size": "20"}, {"price": "0.48", "size": "10"}],
            "asks": [{"price": "0.52", "size": "25"}],
        },
    }])
    execution_payload = {
        "event_type": "last_trade_price",
        "asset_id": "yes-1",
        "market": "condition-1",
        "price": "0.49",
        "size": "2",
        "side": "SELL",
        "transaction_hash": "0xstrictthrough1",
        "timestamp": str(int((quote_time + timedelta(seconds=20)).timestamp() * 1000)),
        "trade_time_utc": (quote_time + timedelta(seconds=20)).isoformat(),
    }
    execution_sha1 = payload_sha1(execution_payload)
    _write_jsonl(folder / EXECUTION_RAW_TAPE_FILENAME, [{
        "schema_version": RAW_EXECUTION_SCHEMA_VERSION,
        "received_at_utc": (quote_time + timedelta(seconds=21)).isoformat(),
        "event_slug": event_slug,
        "market_id": "testville",
        "session_id": "session-1",
        "local_connection_message_sequence": 1,
        "connection_sequence_scope": CONNECTION_SEQUENCE_SCOPE,
        "book_alignment_sequence_status": BOOK_ALIGNMENT_SEQUENCE_STATUS,
        "raw_sha1": execution_sha1,
        "payload": execution_payload,
    }])
    canonical_row = {column: "" for column in EXECUTION_TAPE_COLUMNS}
    exchange_time_utc = (quote_time + timedelta(seconds=20)).isoformat(
        timespec="milliseconds"
    )
    canonical_row.update({
        "schema_version": EXECUTION_ROW_SCHEMA_VERSION,
        "received_at_utc": (quote_time + timedelta(seconds=21)).isoformat(),
        "exchange_time_utc": exchange_time_utc,
        "trade_time_utc": exchange_time_utc,
        "timestamp_utc": exchange_time_utc,
        "exchange_timestamp_ms": execution_payload["timestamp"],
        "timestamp_precision_seconds": "0.001",
        "event_slug": event_slug,
        "market_id": "testville",
        "event_type": "last_trade_price",
        "asset_id": "yes-1",
        "clob_token_id": "yes-1",
        "market": "condition-1",
        "condition_id": "condition-1",
        "price": "0.49",
        "size": "2",
        "side": "SELL",
        "transaction_hash": "0xstrictthrough1",
        "session_id": "session-1",
        "local_connection_message_sequence": "1",
        "connection_sequence_scope": CONNECTION_SEQUENCE_SCOPE,
        "book_alignment_sequence_status": BOOK_ALIGNMENT_SEQUENCE_STATUS,
        "raw_sha1": execution_sha1,
    })
    _write_csv(folder / EXECUTION_CANONICAL_TAPE_FILENAME, [canonical_row])
    _write_bound_receipt(
        folder,
        event_slug=event_slug,
        assets=["yes-1"],
        start=quote_time - timedelta(minutes=5),
        end=quote_time + timedelta(minutes=5),
        execution_count=1,
        message_count=1,
    )
    _write_csv(folder / "order_books_summary.csv", [{
        "captured_at_utc": (quote_time - timedelta(seconds=10)).isoformat(),
        "event_slug": event_slug,
        "market_id": "testville",
        "range_label": "80-81 F",
        "bin_kind": "eq",
        "bin_value": "80",
        "bin_value_hi": "81",
        "clob_token_id": "yes-1",
        "best_bid": "0.50",
        "best_ask": "0.52",
        "midpoint": "0.51",
        "bid_size_at_best": "5",
        "ask_size_at_best": "5",
        "tick_size": "0.01",
    }])
    _write_csv(folder / "price_history.csv", [
        {
            "point_time_utc": (quote_time + timedelta(seconds=50)).isoformat(),
            "clob_token_id": "yes-1",
            "price": "0.52",
        },
        {
            "point_time_utc": (quote_time + timedelta(minutes=1, seconds=20)).isoformat(),
            "clob_token_id": "yes-1",
            "price": "0.53",
        },
        {
            "point_time_utc": (quote_time + timedelta(minutes=5, seconds=20)).isoformat(),
            "clob_token_id": "yes-1",
            "price": "0.54",
        },
        {
            "point_time_utc": (quote_time + timedelta(minutes=30, seconds=30)).isoformat(),
            "clob_token_id": "yes-1",
            "price": "0.55",
        },
    ])
    (folder / "settlement.json").write_text(json.dumps({
        "event_slug": event_slug,
        "market_id": "testville",
        "settlement_bucket": 80,
        "winning_band": "80-81 F",
    }), encoding="utf-8")
    return quote, leg


def test_constructive_day_shaped_proof_is_countable(tmp_path):
    quote, leg = _constructive_inputs(tmp_path)
    config = {**DEFAULT_CONFIG, "fill_evidence_require_clob_recon_coverage": False}
    fills, _queues, diagnostics, _ = simulate_conservative_fills(
        [leg],
        tmp_path,
        {},
        config,
    )
    assert diagnostics[leg["event_slug"]]["trade_rows"] == 1
    assert len(fills) == 1
    assert EXECUTION_RAW_TAPE_FILENAME in fills[0]["execution_source_representations"]
    assert EXECUTION_CANONICAL_TAPE_FILENAME in fills[0]["execution_source_representations"]
    assert json.loads(fills[0]["execution_audit_bindings_json"]) == [{
        "connection_sequence_scope": CONNECTION_SEQUENCE_SCOPE,
        "local_connection_message_sequence": 1,
        "raw_sha1": fills[0]["execution_raw_sha1"],
        "session_id": "session-1",
    }]
    assert fills[0]["conservative_fill_rule"] == "strict_trade_through_price_and_recorded_size"
    assert fills[0]["acceptance_pnl_status"] == "COUNTABLE_SETTLEMENT"
    reward = build_sampled_reward_q_share(
        [leg],
        tmp_path,
        discount_factor=0.3,
        default_tick_size=0.01,
        default_min_order_size=1.0,
    )
    assert reward["status"] == "PASS"
    assert reward["competitor_q"] == pytest.approx(6.9)
    assert reward["own_q"] == pytest.approx(10.0)
    assert reward["sampled_q_share"] == pytest.approx(10.0 / 16.9)
    assert reward["samples"][0]["capture_id"] == "book-1"

    countability = build_day_countability(
        [quote],
        [leg],
        fills,
        snapshots_root=tmp_path,
        fill_evidence={"status": "PASS", "blockers": []},
        reward_q_share=reward,
        reservation_gate=_clear_reservation_gate(),
    )
    assert countability["status"] == "COUNTABLE"
    assert countability["counts_toward_maker_day_target"] is True
    assert all(countability["checklist"].values())


def test_explicit_target_date_isolated_from_multi_day_paper_corpus(tmp_path):
    quote, leg = _constructive_inputs(tmp_path)
    config = {**DEFAULT_CONFIG, "fill_evidence_require_clob_recon_coverage": False}
    fills, _queues, _diagnostics, _ = simulate_conservative_fills(
        [leg],
        tmp_path,
        {},
        config,
    )
    reward = build_sampled_reward_q_share([leg], tmp_path, discount_factor=0.3)
    other_quote = {
        "target_date": "2026-08-03",
        "event_slug": "highest-temperature-in-elsewhere-on-august-3-2026",
        "market_id": "elsewhere",
        "generated_at_utc": "2026-08-03T14:00:00+00:00",
    }
    multi_day_fill_evidence = {
        "status": "BLOCK",
        "blockers": ["rejected_execution_evidence_rows"],
        "by_target_date": {
            "2026-08-03": {
                "status": "BLOCK",
                "blockers": ["rejected_execution_evidence_rows"],
            },
            "2026-08-04": {"status": "PASS", "blockers": []},
        },
    }

    aggregate = build_day_countability(
        [other_quote, quote],
        [leg],
        fills,
        snapshots_root=tmp_path,
        fill_evidence=multi_day_fill_evidence,
        reward_q_share=reward,
        reservation_gate=_clear_reservation_gate(),
    )
    selected = build_day_countability(
        [other_quote, quote],
        [leg],
        fills,
        snapshots_root=tmp_path,
        fill_evidence=multi_day_fill_evidence,
        reward_q_share=reward,
        target_date="2026-08-04",
        reservation_gate=_clear_reservation_gate(),
    )

    assert aggregate["status"] == "NOT_COUNTABLE"
    assert "expected_exactly_one_target_date" in aggregate["blockers"]
    assert selected["status"] == "COUNTABLE"
    assert selected["target_dates"] == ["2026-08-04"]
    assert selected["reward_q_share"]["status"] == "PASS"
    assert selected["fill_evidence"]["status"] == "PASS"
    assert not any(
        blocker.startswith("fill_evidence:") for blocker in selected["blockers"]
    )


def test_missing_unbound_execution_evidence_never_counts_even_for_valid_abstention(tmp_path):
    quote = {
        "target_date": "2026-08-04",
        "event_slug": "highest-temperature-in-testville-on-august-4-2026",
        "market_id": "testville",
    }
    result = build_day_countability(
        [quote],
        [],
        [],
        snapshots_root=tmp_path,
        fill_evidence={"status": "BLOCK", "blockers": ["no_quote_legs"]},
        reward_q_share={"status": "NOT_APPLICABLE", "exact_sampled": True},
        reservation_gate=_clear_reservation_gate(),
    )
    assert result["status"] == "NOT_COUNTABLE"
    assert any(blocker.startswith("execution_tape_missing:") for blocker in result["blockers"])
    assert "fill_evidence:no_quote_legs" not in result["blockers"]


def test_bound_exact_zero_receipt_allows_missing_tapes_for_valid_abstention(tmp_path):
    event_slug = "highest-temperature-in-testville-on-august-4-2026"
    folder = tmp_path / event_slug
    decision_time = datetime(2026, 8, 4, 14, 0, tzinfo=UTC)
    _write_jsonl(folder / "order_books.jsonl", [{"capture_id": "book-zero"}])
    _write_bound_receipt(
        folder,
        event_slug=event_slug,
        assets=["yes-1"],
        start=decision_time - timedelta(minutes=5),
        end=decision_time + timedelta(minutes=5),
        execution_count=0,
        message_count=7,
    )
    quote = {
        "target_date": "2026-08-04",
        "event_slug": event_slug,
        "market_id": "testville",
        "clob_token_id": "yes-1",
        "generated_at_utc": decision_time.isoformat(),
    }
    result = build_day_countability(
        [quote],
        [],
        [],
        snapshots_root=tmp_path,
        fill_evidence={"status": "BLOCK", "blockers": ["no_quote_legs"]},
        reward_q_share={"status": "NOT_APPLICABLE", "exact_sampled": True},
        reservation_gate=_clear_reservation_gate(),
    )
    assert result["status"] == "COUNTABLE"
    event = result["execution_tape_inventory"]["events"][0]
    assert event["execution_tape_present"] is False
    assert event["execution_zero_proven"] is True
    assert event["execution_evidence_complete"] is True


def test_exact_zero_receipt_requires_complete_per_event_asset_readiness(tmp_path):
    event_slug = "highest-temperature-in-testville-on-august-4-2026"
    folder = tmp_path / event_slug
    decision_time = datetime(2026, 8, 4, 14, 0, tzinfo=UTC)
    _write_jsonl(folder / "order_books.jsonl", [{"capture_id": "book-zero"}])
    receipt = _write_bound_receipt(
        folder,
        event_slug=event_slug,
        assets=["yes-1", "no-1"],
        start=decision_time - timedelta(minutes=5),
        end=decision_time + timedelta(minutes=5),
        execution_count=0,
        message_count=7,
    )
    receipt["observed_subscribed_asset_ids"] = ["yes-1"]
    receipt["observed_subscribed_asset_count"] = 1
    receipt["observed_subscribed_asset_set_sha256"] = _asset_set_sha256(["yes-1"])
    receipt["receipt_binding_sha256"] = _receipt_binding_sha256(receipt)
    _write_jsonl(folder / EXECUTION_SESSION_FILENAME, [receipt])
    quote = {
        "target_date": "2026-08-04",
        "event_slug": event_slug,
        "market_id": "testville",
        "clob_token_id": "yes-1",
        "generated_at_utc": decision_time.isoformat(),
    }

    inventory = build_execution_tape_inventory([quote], [], tmp_path)

    assert inventory["status"] == "BLOCK"
    assert any(
        "observed_subscribed_asset_binding_invalid" in blocker
        for blocker in inventory["blockers"]
    )


def test_positive_receipt_requires_both_matching_tapes(tmp_path):
    quote, leg = _constructive_inputs(tmp_path)
    folder = tmp_path / leg["event_slug"]
    (folder / EXECUTION_CANONICAL_TAPE_FILENAME).unlink()
    inventory = build_execution_tape_inventory([quote], [leg], tmp_path)
    assert inventory["status"] == "BLOCK"
    assert any(
        "canonical_tape_missing" in blocker or "positive_execution_tape_missing" in blocker
        for blocker in inventory["blockers"]
    )


def test_bound_prefix_hash_detects_tampering_but_allows_later_append(tmp_path):
    quote, leg = _constructive_inputs(tmp_path)
    folder = tmp_path / leg["event_slug"]
    raw_path = folder / EXECUTION_RAW_TAPE_FILENAME
    raw_path.write_bytes(raw_path.read_bytes() + b'{"later":"unbound"}\n')
    later = build_execution_tape_inventory([quote], [leg], tmp_path)
    assert later["status"] == "PASS"

    original = raw_path.read_bytes()
    raw_path.write_bytes(original.replace(b'"0.49"', b'"0.48"', 1))
    tampered = build_execution_tape_inventory([quote], [leg], tmp_path)
    assert tampered["status"] == "BLOCK"
    assert any("raw_prefix_hash_mismatch" in blocker for blocker in tampered["blockers"])


def test_receipt_rejects_rows_outside_local_sequence_interval(tmp_path):
    quote, leg = _constructive_inputs(tmp_path)
    folder = tmp_path / leg["event_slug"]
    raw_path = folder / EXECUTION_RAW_TAPE_FILENAME
    canonical_path = folder / EXECUTION_CANONICAL_TAPE_FILENAME
    raw = json.loads(raw_path.read_text(encoding="utf-8").strip())
    raw["local_connection_message_sequence"] = 999
    _write_jsonl(raw_path, [raw])
    rows = list(csv.DictReader(canonical_path.read_text(encoding="utf-8").splitlines()))
    rows[0]["local_connection_message_sequence"] = "999"
    _write_csv(canonical_path, rows)
    _rebind_existing_receipt(folder)

    inventory = build_execution_tape_inventory([quote], [leg], tmp_path)

    assert inventory["status"] == "BLOCK"
    assert any(
        "raw_execution_row_invalid" in blocker
        or "canonical_execution_row_invalid" in blocker
        for blocker in inventory["blockers"]
    )


def test_receipt_rejects_semantically_mismatched_canonical_projection(tmp_path):
    quote, leg = _constructive_inputs(tmp_path)
    folder = tmp_path / leg["event_slug"]
    canonical_path = folder / EXECUTION_CANONICAL_TAPE_FILENAME
    rows = list(csv.DictReader(canonical_path.read_text(encoding="utf-8").splitlines()))
    rows[0]["transaction_hash"] = "0xdifferent"
    rows[0]["exchange_time_utc"] = "2026-08-04T14:00:21.000+00:00"
    _write_csv(canonical_path, rows)
    _rebind_existing_receipt(folder)

    inventory = build_execution_tape_inventory([quote], [leg], tmp_path)

    assert inventory["status"] == "BLOCK"
    assert any(
        "execution_representation_semantic_mismatch" in blocker
        for blocker in inventory["blockers"]
    )


def test_fill_cannot_borrow_another_bound_execution_audit_key(tmp_path):
    quote, leg = _constructive_inputs(tmp_path)
    folder = tmp_path / leg["event_slug"]
    raw_path = folder / EXECUTION_RAW_TAPE_FILENAME
    canonical_path = folder / EXECUTION_CANONICAL_TAPE_FILENAME
    first_raw = json.loads(raw_path.read_text(encoding="utf-8").strip())
    first_canonical = next(
        csv.DictReader(canonical_path.read_text(encoding="utf-8").splitlines())
    )
    config = {**DEFAULT_CONFIG, "fill_evidence_require_clob_recon_coverage": False}
    fills, _queues, _diagnostics, _ = simulate_conservative_fills(
        [leg],
        tmp_path,
        {},
        config,
    )
    assert len(fills) == 1

    second_payload = {
        **first_raw["payload"],
        "price": "0.47",
        "transaction_hash": "0xstrictthrough2",
        "timestamp": str(int((leg["quote_time"] + timedelta(seconds=21)).timestamp() * 1000)),
    }
    second_sha1 = payload_sha1(second_payload)
    second_raw = {
        **first_raw,
        "received_at_utc": (leg["quote_time"] + timedelta(seconds=22)).isoformat(),
        "local_connection_message_sequence": 2,
        "raw_sha1": second_sha1,
        "payload": second_payload,
    }
    second_time = (leg["quote_time"] + timedelta(seconds=21)).isoformat(
        timespec="milliseconds"
    )
    second_canonical = {
        **first_canonical,
        "received_at_utc": second_raw["received_at_utc"],
        "exchange_time_utc": second_time,
        "trade_time_utc": second_time,
        "timestamp_utc": second_time,
        "exchange_timestamp_ms": second_payload["timestamp"],
        "price": second_payload["price"],
        "transaction_hash": second_payload["transaction_hash"],
        "local_connection_message_sequence": "2",
        "raw_sha1": second_sha1,
    }
    _write_jsonl(raw_path, [first_raw, second_raw])
    _write_csv(canonical_path, [first_canonical, second_canonical])
    receipt_path = folder / EXECUTION_SESSION_FILENAME
    receipt = json.loads(receipt_path.read_text(encoding="utf-8").strip())
    receipt["execution_count"] = 2
    receipt["message_count"] = 2
    receipt["market_data_message_count"] = 2
    receipt["local_connection_message_sequence_end"] = 2
    receipt["receipt_binding_sha256"] = _receipt_binding_sha256(receipt)
    _write_jsonl(receipt_path, [receipt])
    _rebind_existing_receipt(folder)

    fills[0]["execution_raw_sha1"] = second_sha1
    fills[0]["execution_audit_bindings_json"] = json.dumps([{
        "session_id": second_raw["session_id"],
        "local_connection_message_sequence": 2,
        "raw_sha1": second_sha1,
        "connection_sequence_scope": CONNECTION_SEQUENCE_SCOPE,
    }])
    inventory = build_execution_tape_inventory(
        [quote],
        [leg],
        tmp_path,
        fill_rows=fills,
    )

    assert inventory["status"] == "BLOCK"
    assert any(
        blocker.startswith("execution_fill_not_bound:")
        for blocker in inventory["blockers"]
    )


def test_receipt_rejects_execution_missing_scorer_required_identity(tmp_path):
    quote, leg = _constructive_inputs(tmp_path)
    folder = tmp_path / leg["event_slug"]
    raw_path = folder / EXECUTION_RAW_TAPE_FILENAME
    canonical_path = folder / EXECUTION_CANONICAL_TAPE_FILENAME
    raw = json.loads(raw_path.read_text(encoding="utf-8").strip())
    raw["payload"].pop("transaction_hash")
    raw["raw_sha1"] = payload_sha1(raw["payload"])
    _write_jsonl(raw_path, [raw])
    rows = list(csv.DictReader(canonical_path.read_text(encoding="utf-8").splitlines()))
    rows[0]["transaction_hash"] = ""
    rows[0]["raw_sha1"] = raw["raw_sha1"]
    _write_csv(canonical_path, rows)
    _rebind_existing_receipt(folder)

    inventory = build_execution_tape_inventory([quote], [leg], tmp_path)

    assert inventory["status"] == "BLOCK"
    assert any(
        "execution_representation_semantic_mismatch" in blocker
        for blocker in inventory["blockers"]
    )


def test_receipt_cannot_hide_same_session_row_under_wrong_event(tmp_path):
    quote, leg = _constructive_inputs(tmp_path)
    folder = tmp_path / leg["event_slug"]
    raw_path = folder / EXECUTION_RAW_TAPE_FILENAME
    canonical_path = folder / EXECUTION_CANONICAL_TAPE_FILENAME
    raw = json.loads(raw_path.read_text(encoding="utf-8").strip())
    raw["event_slug"] = "wrong-event"
    _write_jsonl(raw_path, [raw])
    rows = list(csv.DictReader(canonical_path.read_text(encoding="utf-8").splitlines()))
    rows[0]["event_slug"] = "wrong-event"
    _write_csv(canonical_path, rows)
    receipt_path = folder / EXECUTION_SESSION_FILENAME
    receipt = json.loads(receipt_path.read_text(encoding="utf-8").strip())
    receipt["execution_count"] = 0
    receipt["receipt_binding_sha256"] = _receipt_binding_sha256(receipt)
    _write_jsonl(receipt_path, [receipt])
    _rebind_existing_receipt(folder)

    inventory = build_execution_tape_inventory([quote], [leg], tmp_path)

    assert inventory["status"] == "BLOCK"
    assert any(
        "execution_receipt_count_mismatch" in blocker
        or "raw_execution_row_invalid" in blocker
        for blocker in inventory["blockers"]
    )


def test_complete_zero_message_receipt_cannot_prove_exact_zero(tmp_path):
    event_slug = "highest-temperature-in-testville-on-august-4-2026"
    folder = tmp_path / event_slug
    decision_time = datetime(2026, 8, 4, 14, 0, tzinfo=UTC)
    _write_jsonl(folder / "order_books.jsonl", [{"capture_id": "book-zero"}])
    _write_bound_receipt(
        folder,
        event_slug=event_slug,
        assets=["yes-1"],
        start=decision_time - timedelta(minutes=5),
        end=decision_time + timedelta(minutes=5),
        execution_count=0,
        message_count=0,
    )
    quote = {
        "target_date": "2026-08-04",
        "event_slug": event_slug,
        "market_id": "testville",
        "clob_token_id": "yes-1",
        "generated_at_utc": decision_time.isoformat(),
    }

    inventory = build_execution_tape_inventory([quote], [], tmp_path)

    assert inventory["status"] == "BLOCK"
    assert any(
        "complete_session_without_inbound_liveness" in blocker
        for blocker in inventory["blockers"]
    )


def test_zero_message_receipt_still_requires_local_connection_scope(tmp_path):
    event_slug = "highest-temperature-in-testville-on-august-4-2026"
    folder = tmp_path / event_slug
    decision_time = datetime(2026, 8, 4, 14, 0, tzinfo=UTC)
    receipt = _write_bound_receipt(
        folder,
        event_slug=event_slug,
        assets=["yes-1"],
        start=decision_time - timedelta(minutes=5),
        end=decision_time + timedelta(minutes=5),
        execution_count=0,
        message_count=0,
    )
    receipt["connection_sequence_scope"] = "book-alignment-sequence"
    receipt["receipt_binding_sha256"] = _receipt_binding_sha256(receipt)
    _write_jsonl(folder / EXECUTION_SESSION_FILENAME, [receipt])
    quote = {
        "target_date": "2026-08-04",
        "event_slug": event_slug,
        "market_id": "testville",
        "clob_token_id": "yes-1",
        "generated_at_utc": decision_time.isoformat(),
    }

    inventory = build_execution_tape_inventory([quote], [], tmp_path)

    assert inventory["status"] == "BLOCK"
    assert any(
        "connection_sequence_scope_invalid" in blocker
        for blocker in inventory["blockers"]
    )


@pytest.mark.parametrize("source_mode", ["unbound_dedicated", "legacy_only"])
def test_countability_rejects_fill_outside_complete_bound_execution_receipt(
    tmp_path,
    source_mode,
):
    quote, leg = _constructive_inputs(tmp_path)
    folder = tmp_path / leg["event_slug"]
    raw_path = folder / EXECUTION_RAW_TAPE_FILENAME
    canonical_path = folder / EXECUTION_CANONICAL_TAPE_FILENAME
    raw_row = json.loads(raw_path.read_text(encoding="utf-8").strip())
    canonical_row = next(csv.DictReader(canonical_path.read_text(encoding="utf-8").splitlines()))
    raw_path.unlink()
    canonical_path.unlink()
    _write_bound_receipt(
        folder,
        event_slug=leg["event_slug"],
        assets=["yes-1"],
        start=leg["quote_time"] - timedelta(minutes=5),
        end=leg["quote_expires_at"] + timedelta(minutes=5),
        execution_count=0,
        message_count=1,
    )
    if source_mode == "unbound_dedicated":
        _write_jsonl(raw_path, [raw_row])
        _write_csv(canonical_path, [canonical_row])
    else:
        _write_jsonl(folder / "market_ws.jsonl", [raw_row])
        _write_csv(folder / "market_ws_events.csv", [canonical_row])

    config = {**DEFAULT_CONFIG, "fill_evidence_require_clob_recon_coverage": False}
    fills, _queues, _diagnostics, _ = simulate_conservative_fills(
        [leg],
        tmp_path,
        {},
        config,
    )
    assert len(fills) == 1
    reward = build_sampled_reward_q_share([leg], tmp_path, discount_factor=0.3)
    result = build_day_countability(
        [quote],
        [leg],
        fills,
        snapshots_root=tmp_path,
        fill_evidence={"status": "PASS", "blockers": []},
        reward_q_share=reward,
        reservation_gate=_clear_reservation_gate(),
    )

    assert result["status"] == "NOT_COUNTABLE"
    assert any(
        blocker.startswith("execution_fill_not_bound:")
        for blocker in result["blockers"]
    )


def test_missing_settlement_cannot_fall_back_to_30m_for_countability(tmp_path):
    quote, leg = _constructive_inputs(tmp_path)
    reward = build_sampled_reward_q_share([leg], tmp_path, discount_factor=0.3)
    result = build_day_countability(
        [quote],
        [leg],
        [{
            "fill_id": "fill-1",
            "target_date": "2026-08-04",
            "acceptance_pnl_status": "NOT_COUNTABLE_SETTLEMENT_MISSING",
            "conservative_fill_rule": "strict_trade_through_price_and_recorded_size",
            "provisional_net_30m_usdc": 1.25,
        }],
        snapshots_root=tmp_path,
        fill_evidence={"status": "PASS", "blockers": []},
        reward_q_share=reward,
        reservation_gate=_clear_reservation_gate(),
    )
    assert result["status"] == "NOT_COUNTABLE"
    assert "settlement_horizon_missing=1" in result["blockers"]


def test_confirmation_reservation_gate_stops_declared_dates(tmp_path):
    undated = tmp_path / "undated.md"
    undated.write_text(
        "| **Reserved dates** | **NONE ARE CURRENTLY RESERVED.** |\n",
        encoding="utf-8",
    )
    declared = tmp_path / "declared.md"
    declared.write_text(
        "| **Reserved dates** | **2026-08-06 through 2026-11-03** |\n",
        encoding="utf-8",
    )

    assert confirmation_reservation_gate("2026-08-07", path=undated)["status"] == "PASS"
    blocked = confirmation_reservation_gate("2026-08-07", path=declared)
    outside = confirmation_reservation_gate("2026-08-05", path=declared)
    missing_target = confirmation_reservation_gate(path=declared)

    assert blocked["status"] == "BLOCK"
    assert blocked["blockers"] == ["target_date_reserved_for_confirmation"]
    assert outside["status"] == "PASS"
    assert missing_target["status"] == "BLOCK"
    assert missing_target["blockers"] == [
        "explicit_target_required_while_confirmation_reserved"
    ]
