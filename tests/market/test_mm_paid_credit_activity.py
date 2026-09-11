"""Behavioral fixtures for supplied activity/Polygon receipt evidence joins."""

from copy import deepcopy
from datetime import datetime
from decimal import localcontext
import hashlib
import json
from urllib.parse import urlencode

import pytest

from weather.market.mm_paid_credit_activity import (
    MAX_CAPTURE_BYTES,
    PUSD_COLLATERAL_PROXY_ADDRESS,
    TRANSFER_TOPIC,
    bridge_activity_credits,
)


ACCOUNT = "0x" + "1" * 40
SENDER = "0x" + "2" * 40
CONDITION = "0x" + "3" * 64
TX = "0x" + "4" * 64
BLOCK = "0x" + "5" * 64
FINAL_BLOCK = "0x" + "6" * 64
START = "2026-09-06T00:00:00+00:00"
END = "2026-09-06T00:10:00+00:00"
AS_OF = "2026-09-06T00:30:00+00:00"
START_EPOCH = int(datetime.fromisoformat(START).timestamp())


def _body(capture, payload=None, *, raw=None):
    text = json.dumps(payload) if raw is None else raw
    capture["raw_response"] = text
    capture["raw_response_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()


def _capture(source, request, payload, observed):
    capture = {
        "source_id": source, "request": request, "observed_at_utc": observed,
        "http_status": 200,
    }
    _body(capture, payload)
    return capture


def _rpc(method, params, result, observed):
    return _capture(
        "supplied-polygon-rpc",
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        {"jsonrpc": "2.0", "id": 1, "result": result}, observed,
    )


def _fixture():
    row = {
        "proxyWallet": ACCOUNT, "timestamp": START_EPOCH + 300,
        "conditionId": CONDITION, "type": "MAKER_REBATE", "usdcSize": 1.25,
        "transactionHash": TX, "asset": "", "size": 0,
    }
    query = urlencode({
        "user": ACCOUNT, "start": START_EPOCH, "end": START_EPOCH + 600,
        "limit": 500, "offset": 0, "sortBy": "TIMESTAMP", "sortDirection": "ASC",
        "excludeDepositsWithdrawals": "false",
    })
    log = {
        "address": PUSD_COLLATERAL_PROXY_ADDRESS,
        "topics": [TRANSFER_TOPIC, "0x" + "0" * 24 + SENDER[2:], "0x" + "0" * 24 + ACCOUNT[2:]],
        "data": "0x" + format(1_250_000, "064x"), "logIndex": "0x3",
        "transactionHash": TX, "transactionIndex": "0x0", "blockHash": BLOCK,
        "blockNumber": "0x64", "removed": False,
    }
    receipt = {
        "transactionHash": TX, "status": "0x1", "blockNumber": "0x64",
        "blockHash": BLOCK, "transactionIndex": "0x0", "logs": [log],
    }
    block = {"number": "0x64", "hash": BLOCK, "timestamp": hex(START_EPOCH + 300), "transactions": [TX]}
    final = {"number": "0x65", "hash": FINAL_BLOCK, "timestamp": hex(START_EPOCH + 302)}
    return {
        "scope": {
            "maker_address": ACCOUNT, "condition_id": CONDITION, "chain_id": 137,
            "asset_address": PUSD_COLLATERAL_PROXY_ADDRESS, "asset_decimals": 6,
            "activity_start_utc": START, "activity_end_utc": END, "as_of_utc": AS_OF,
        },
        "activity_captures": [_capture(
            "supplied-polymarket-activity", {"method": "GET", "url": "https://data-api.polymarket.com/activity?" + query},
            [row], "2026-09-06T00:25:00+00:00",
        )],
        "rpc_captures": [
            _rpc("eth_chainId", [], "0x89", "2026-09-06T00:18:00+00:00"),
            _rpc("eth_getTransactionReceipt", [TX], receipt, "2026-09-06T00:19:00+00:00"),
            _rpc("eth_getBlockByNumber", ["finalized", False], final, "2026-09-06T00:20:00+00:00"),
            _rpc("eth_getBlockByNumber", ["0x64", False], block, "2026-09-06T00:21:00+00:00"),
        ],
    }


def _activity(evidence, edit):
    capture = evidence["activity_captures"][0]
    rows = json.loads(capture["raw_response"])
    edit(rows)
    _body(capture, rows)


def _rpc_edit(evidence, method, edit, *, params=None):
    capture = next(row for row in evidence["rpc_captures"]
                   if row["request"]["method"] == method
                   and (params is None or row["request"]["params"] == params))
    response = json.loads(capture["raw_response"])
    edit(response["result"])
    _body(capture, response)


def _assert_blocked(result, code=None):
    assert result["status"] in {"INVALID", "UNRESOLVED"}
    assert result["credits"] == []
    assert result["matched_transfer_total_micro_units"] is None
    assert result["matched_transfer_total"] is None
    if code:
        assert result["blockers"] == [code]


def test_unique_finalized_transfer_retains_derived_labels_and_provenance_only():
    evidence = _fixture()
    before = deepcopy(evidence)
    result = bridge_activity_credits(evidence)
    assert evidence == before
    assert result["status"] == "JOINED"
    assert result["matched_transfer_total_micro_units"] == 1_250_000
    assert result["matched_transfer_total"] == "1.250000"
    assert len(result["credits"]) == 1
    credit = result["credits"][0]
    assert credit["credit_id"] == f"137:{TX}:3"
    assert credit["sender"] == SENDER
    assert credit["recipient"] == ACCOUNT
    assert credit["condition_id"] == CONDITION
    assert credit["venue_activity_type"] == "MAKER_REBATE"
    assert credit["label_linkage"] == "DERIVED"
    assert credit["activity_id"].startswith("derived:")
    assert "accrual_id" not in credit and "earned_period" not in credit
    assert "programme" not in credit and "distributions" not in result
    assert len(credit["activity_capture_ids"]) == 1
    assert len(credit["rpc_capture_ids"]) == 4
    assert len(result["provenance"]) == 5
    assert {row["response_sha256"] for row in result["provenance"].values()} == {
        row["raw_response_sha256"] for row in evidence["activity_captures"] + evidence["rpc_captures"]
    }
    for key in ("network_reads_performed", "source_authenticity_verified", "accrual_linkage_verified",
                "account_cash_completeness_verified", "economic_pnl_verified", "live_authority"):
        assert result[key] is False


def test_two_programme_labels_join_separate_transfers_without_accrual_allocation():
    evidence = _fixture()
    tx2 = "0x" + "7" * 64
    _activity(evidence, lambda rows: rows.append({**rows[0], "transactionHash": tx2, "type": "REWARD", "usdcSize": .4}))
    receipt_capture = deepcopy(evidence["rpc_captures"][1])
    receipt_capture["request"]["params"] = [tx2]
    response = json.loads(receipt_capture["raw_response"])
    response["result"].update(transactionHash=tx2, transactionIndex="0x1")
    response["result"]["logs"][0].update(transactionHash=tx2, transactionIndex="0x1", logIndex="0x4", data="0x" + format(400_000, "064x"))
    _body(receipt_capture, response)
    evidence["rpc_captures"].append(receipt_capture)
    _rpc_edit(evidence, "eth_getBlockByNumber", lambda block: block["transactions"].append(tx2), params=["0x64", False])
    result = bridge_activity_credits(evidence)
    assert result["status"] == "JOINED"
    assert result["matched_transfer_total"] == "1.650000"
    assert {row["venue_activity_type"] for row in result["credits"]} == {"REWARD", "MAKER_REBATE"}
    assert result["accrual_linkage_verified"] is False


def test_exact_duplicate_rows_and_captures_are_idempotent_and_order_invariant():
    evidence = _fixture()
    _activity(evidence, lambda rows: rows.append(deepcopy(rows[0])))
    evidence["activity_captures"] *= 2
    evidence["rpc_captures"] *= 2
    result = bridge_activity_credits(evidence)
    assert result["status"] == "JOINED"
    assert result["matched_transfer_total_micro_units"] == 1_250_000
    assert result["duplicate_activity_count"] == 3
    assert result["duplicate_rpc_capture_count"] == 4
    evidence["activity_captures"].reverse()
    evidence["rpc_captures"].reverse()
    assert bridge_activity_credits(evidence) == result


@pytest.mark.parametrize("field,value", [
    ("chain_id", 1), ("chain_id", True), ("asset_decimals", 18), ("asset_decimals", 6.0),
    ("asset_address", SENDER), ("maker_address", "unknown"), ("condition_id", ACCOUNT),
    ("activity_end_utc", START), ("activity_start_utc", "2026-09-06T00:00:00"),
    ("activity_end_utc", "2026-09-06T00:10:00.001+00:00"),
])
def test_scope_requires_exact_account_condition_chain_asset_and_time(field, value):
    evidence = _fixture()
    evidence["scope"][field] = value
    _assert_blocked(bridge_activity_credits(evidence))


@pytest.mark.parametrize("field,value", [
    ("proxyWallet", SENDER), ("conditionId", "0x" + "8" * 64), ("conditionId", ""),
    ("transactionHash", "not-a-hash"), ("timestamp", START_EPOCH - 1),
    ("timestamp", START_EPOCH + 601), ("timestamp", True),
])
def test_activity_scope_errors_do_not_produce_credit(field, value):
    evidence = _fixture()
    _activity(evidence, lambda rows: rows[0].update({field: value}))
    _assert_blocked(bridge_activity_credits(evidence))


@pytest.mark.parametrize("literal", ["0", "-1", "true", '"1.25"', "1.0000001", "1e1000", "1e-1000", "NaN", "Infinity"])
def test_raw_amount_must_be_positive_exact_json_number(literal):
    evidence = _fixture()
    capture = evidence["activity_captures"][0]
    _body(capture, raw=capture["raw_response"].replace('"usdcSize": 1.25', '"usdcSize": ' + literal))
    _assert_blocked(bridge_activity_credits(evidence))


@pytest.mark.parametrize("capture_kind", ["activity", "rpc"])
@pytest.mark.parametrize("literal", ["1e9999999999999999999", "1e-9999999999999999999"])
def test_decimal_constructor_failure_returns_invalid_for_any_capture(capture_kind, literal):
    evidence = _fixture()
    if capture_kind == "activity":
        capture = evidence["activity_captures"][0]
        raw = capture["raw_response"].replace('"usdcSize": 1.25', '"usdcSize": ' + literal)
    else:
        capture = evidence["rpc_captures"][0]
        raw = capture["raw_response"].replace('"result": "0x89"', '"result": ' + literal)
    assert literal in raw
    _body(capture, raw=raw)
    result = bridge_activity_credits(evidence)
    assert result["status"] == "INVALID"
    _assert_blocked(result, "capture_json_invalid")


@pytest.mark.parametrize("literal,units", [
    ("1.000001000000", 1_000_001), ("9007199254.740993", 9_007_199_254_740_993),
])
def test_raw_decimal_keeps_micro_units_under_low_ambient_precision(literal, units):
    evidence = _fixture()
    capture = evidence["activity_captures"][0]
    _body(capture, raw=capture["raw_response"].replace('"usdcSize": 1.25', '"usdcSize": ' + literal))
    _rpc_edit(evidence, "eth_getTransactionReceipt", lambda receipt: receipt["logs"][0].update(data="0x" + format(units, "064x")))
    with localcontext() as context:
        context.prec = 1
        result = bridge_activity_credits(evidence)
    assert result["status"] == "JOINED"
    assert result["matched_transfer_total_micro_units"] == units


def test_activity_token_id_is_not_used_as_collateral_identity():
    evidence = _fixture()
    _activity(evidence, lambda rows: rows[0].update(asset="1234567890"))
    assert bridge_activity_credits(evidence)["status"] == "JOINED"


@pytest.mark.parametrize("field,value", [
    ("source_id", "https://unreviewed.example/rpc"), ("raw_response_sha256", "0" * 64),
    ("http_status", True), ("http_status", 500), ("observed_at_utc", "2026-09-06T00:31:00+00:00"),
    ("observed_at_utc", "2026-09-06T00:09:00+00:00"),
])
def test_capture_provenance_is_required_but_never_authenticated(field, value):
    evidence = _fixture()
    evidence["activity_captures"][0][field] = value
    _assert_blocked(bridge_activity_credits(evidence))


@pytest.mark.parametrize("old,new", [
    ("data-api.polymarket.com", "attacker.example"), ("offset=0", "offset=5001"),
    ("limit=500", "limit=501"), ("excludeDepositsWithdrawals=false", "excludeDepositsWithdrawals=true"),
    ("sortDirection=ASC", "sortDirection=DESC"), ("/activity?", "/activity?market=" + CONDITION + "&"),
])
def test_activity_request_is_exact_and_bounded(old, new):
    evidence = _fixture()
    request = evidence["activity_captures"][0]["request"]
    request["url"] = request["url"].replace(old, new)
    _assert_blocked(bridge_activity_credits(evidence))


def test_wrong_rpc_chain_and_mismatched_response_id_fail():
    for edit in (lambda body: body.update(result="0x1"), lambda body: body.update(id=2)):
        evidence = _fixture()
        capture = evidence["rpc_captures"][0]
        body = json.loads(capture["raw_response"])
        edit(body)
        _body(capture, body)
        _assert_blocked(bridge_activity_credits(evidence))


@pytest.mark.parametrize("field,value", [
    ("status", "0x0"), ("status", "0x2"), ("status", True),
    ("transactionHash", "0x" + "9" * 64), ("blockHash", "0x" + "9" * 64),
    ("transactionIndex", "0x1"), ("logs", None),
])
def test_receipt_must_be_successful_and_bound_to_the_transaction(field, value):
    evidence = _fixture()
    _rpc_edit(evidence, "eth_getTransactionReceipt", lambda receipt: receipt.update({field: value}))
    _assert_blocked(bridge_activity_credits(evidence))


@pytest.mark.parametrize("field,value", [
    ("address", SENDER), ("removed", True), ("removed", None),
    ("transactionHash", "0x" + "9" * 64), ("blockHash", "0x" + "9" * 64),
    ("blockNumber", "0x65"), ("transactionIndex", "0x1"),
    ("data", "0x" + format(1_250_001, "064x")), ("data", "0x1"),
])
def test_transfer_must_have_exact_asset_amount_and_log_context(field, value):
    evidence = _fixture()
    _rpc_edit(evidence, "eth_getTransactionReceipt", lambda receipt: receipt["logs"][0].update({field: value}))
    _assert_blocked(bridge_activity_credits(evidence))


def test_wrong_recipient_and_self_transfer_are_not_paid_credits():
    for topic_index, address in ((2, SENDER), (1, ACCOUNT)):
        evidence = _fixture()
        _rpc_edit(evidence, "eth_getTransactionReceipt", lambda receipt: receipt["logs"][0]["topics"].__setitem__(topic_index, "0x" + "0" * 24 + address[2:]))
        _assert_blocked(bridge_activity_credits(evidence), "activity_transfer_missing_or_ambiguous")


@pytest.mark.parametrize("mutation", ["behind", "same_height_wrong_hash", "canonical_hash", "missing_transaction", "capture_before_finality", "block_after_capture", "block_outside_window"])
def test_canonical_and_finalized_block_evidence_is_required(mutation):
    evidence = _fixture()
    if mutation == "behind":
        _rpc_edit(evidence, "eth_getBlockByNumber", lambda block: block.update(number="0x63"), params=["finalized", False])
    elif mutation == "same_height_wrong_hash":
        _rpc_edit(evidence, "eth_getBlockByNumber", lambda block: block.update(number="0x64"), params=["finalized", False])
    elif mutation == "canonical_hash":
        _rpc_edit(evidence, "eth_getBlockByNumber", lambda block: block.update(hash=FINAL_BLOCK), params=["0x64", False])
    elif mutation == "missing_transaction":
        _rpc_edit(evidence, "eth_getBlockByNumber", lambda block: block.update(transactions=[FINAL_BLOCK]), params=["0x64", False])
    elif mutation == "capture_before_finality":
        evidence["rpc_captures"][3]["observed_at_utc"] = "2026-09-06T00:19:00+00:00"
    elif mutation == "block_after_capture":
        _rpc_edit(evidence, "eth_getBlockByNumber", lambda block: block.update(timestamp=hex(START_EPOCH + 3600)), params=["finalized", False])
    else:
        _rpc_edit(evidence, "eth_getBlockByNumber", lambda block: block.update(timestamp=hex(START_EPOCH - 1)), params=["0x64", False])
    _assert_blocked(bridge_activity_credits(evidence))


def test_two_equal_logs_or_duplicate_log_identity_are_ambiguous():
    for second_index in ("0x4", "0x3"):
        evidence = _fixture()
        _rpc_edit(evidence, "eth_getTransactionReceipt", lambda receipt: receipt["logs"].append({**receipt["logs"][0], "logIndex": second_index}))
        _assert_blocked(bridge_activity_credits(evidence))


@pytest.mark.parametrize("change", [{"type": "REWARD"}, {"timestamp": START_EPOCH + 301}])
def test_two_distinct_activity_labels_cannot_claim_one_credit(change):
    evidence = _fixture()
    _activity(evidence, lambda rows: rows.append({**rows[0], **change}))
    _assert_blocked(bridge_activity_credits(evidence), "transfer_credit_claimed_twice")


def test_aggregate_payment_is_not_split_to_force_two_accrual_labels():
    evidence = _fixture()
    _activity(evidence, lambda rows: rows.append({**rows[0], "type": "REWARD", "usdcSize": .4}))
    _rpc_edit(evidence, "eth_getTransactionReceipt", lambda receipt: receipt["logs"][0].update(data="0x" + format(1_650_000, "064x")))
    _assert_blocked(bridge_activity_credits(evidence), "activity_transfer_missing_or_ambiguous")


def test_equal_amount_does_not_invent_accrual_linkage_or_accept_paid_matcher_shape():
    evidence = _fixture()
    result = bridge_activity_credits(evidence)
    assert result["accrual_linkage_verified"] is False
    assert "accrual_id" not in json.dumps(result)
    assert "period_start_utc" not in json.dumps(result)
    assert "period_end_utc" not in json.dumps(result)
    evidence["accruals"] = [{"date": "2026-09-05", "amount": "1.25"}]
    _assert_blocked(bridge_activity_credits(evidence), "evidence_shape_invalid")


def test_missing_receipts_and_partial_empty_pages_never_prove_zero_cash():
    evidence = _fixture()
    evidence["rpc_captures"] = []
    _assert_blocked(bridge_activity_credits(evidence))
    _body(evidence["activity_captures"][0], [])
    evidence["activity_captures"][0]["request"]["url"] = evidence["activity_captures"][0]["request"]["url"].replace("offset=0", "offset=5000")
    result = bridge_activity_credits(evidence)
    assert result["status"] == "EMPTY_SUBSET"
    assert result["matched_transfer_total_micro_units"] is None
    assert result["account_cash_completeness_verified"] is False


def test_conflicting_repeated_rpc_capture_and_mixed_sources_fail_closed():
    evidence = _fixture()
    conflicting = deepcopy(evidence["rpc_captures"][1])
    body = json.loads(conflicting["raw_response"])
    body["result"]["status"] = "0x0"
    _body(conflicting, body)
    evidence["rpc_captures"].append(conflicting)
    _assert_blocked(bridge_activity_credits(evidence), "rpc_conflicting_capture")
    evidence = _fixture()
    evidence["rpc_captures"][0]["source_id"] = "another-rpc"
    _assert_blocked(bridge_activity_credits(evidence), "required_rpc_capture_missing")


@pytest.mark.parametrize("left,right,field", [
    (False, 0, "removed"), (False, 0, "nested"), (True, 1, "nested"), (1, 1.0, "nested"),
])
@pytest.mark.parametrize("reverse", [False, True])
def test_duplicate_rpc_comparison_preserves_json_types_in_both_orders(left, right, field, reverse):
    evidence = _fixture()

    def set_value(receipt, value):
        if field == "removed":
            receipt["logs"][0]["removed"] = value
        else:
            receipt["additional_metadata"] = {"nested_values": [value]}

    _rpc_edit(evidence, "eth_getTransactionReceipt", lambda receipt: set_value(receipt, left))
    duplicate = deepcopy(evidence["rpc_captures"][1])
    body = json.loads(duplicate["raw_response"])
    set_value(body["result"], right)
    _body(duplicate, body)
    if reverse:
        evidence["rpc_captures"].insert(0, duplicate)
    else:
        evidence["rpc_captures"].append(duplicate)
    _assert_blocked(bridge_activity_credits(evidence), "rpc_conflicting_capture")


def test_raw_hash_duplicate_json_keys_and_bounded_inputs_fail_closed():
    evidence = _fixture()
    capture = evidence["activity_captures"][0]
    capture["raw_response"] += " "
    _assert_blocked(bridge_activity_credits(evidence), "capture_response_hash_mismatch")
    _body(capture, raw=capture["raw_response"].replace('"usdcSize": 1.25', '"usdcSize": 1.25, "usdcSize": 1.25'))
    _assert_blocked(bridge_activity_credits(evidence), "capture_duplicate_json_key")
    _body(capture, raw=" " * (MAX_CAPTURE_BYTES + 1))
    _assert_blocked(bridge_activity_credits(evidence), "capture_size_exceeded")


def test_no_input_file_or_network_execution_is_needed(monkeypatch):
    import socket

    def forbidden(*args, **kwargs):
        raise AssertionError("pure bridge attempted network I/O")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    result = bridge_activity_credits(_fixture())
    assert result["status"] == "JOINED"
    assert result["network_reads_performed"] is False
