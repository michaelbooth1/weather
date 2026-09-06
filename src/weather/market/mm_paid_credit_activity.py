"""Pure, bounded activity-to-pUSD Transfer joins from caller-supplied captures.

This establishes no accrued-period linkage, source authenticity, complete wallet
history, P&L or live authority. See docs/operations/paid-credit-activity-evidence.md.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, DecimalException
from urllib.parse import parse_qsl, urlsplit

from weather.market.mm_official_adapter import PUSD_COLLATERAL_PROXY_ADDRESS


MAX_CAPTURE_BYTES = 256_000
MAX_TOTAL_BYTES = 2_000_000
MAX_CAPTURES = 128
MAX_ACTIVITY_ROWS = 1_000
MAX_RECEIPT_LOGS = 2_000
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ACTIVITY_TYPES = frozenset({"REWARD", "MAKER_REBATE"})
RPC_METHODS = frozenset({"eth_chainId", "eth_getTransactionReceipt", "eth_getBlockByNumber"})
_HEX = re.compile(r"^0x[0-9a-fA-F]+$")
_SHA = re.compile(r"^[0-9a-fA-F]{64}$")
_SOURCE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}$")


class _Invalid(ValueError):
    pass


class _Unresolved(_Invalid):
    pass


def _require(condition, code, *, unresolved=False):
    if not condition:
        raise (_Unresolved if unresolved else _Invalid)(code)


def _hex(value, size, label):
    _require(isinstance(value, str) and len(value) == 2 + size * 2
             and _HEX.fullmatch(value), f"{label}_invalid")
    return value.lower()


def _quantity(value, label):
    _require(isinstance(value, str) and 3 <= len(value) <= 66 and _HEX.fullmatch(value)
             and (len(value) == 3 or value[2] != "0"), f"{label}_invalid")
    return int(value, 16)


def _time(value, label):
    _require(isinstance(value, str) and len(value) <= 40, f"{label}_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _Invalid(f"{label}_invalid") from exc
    _require(parsed.tzinfo is not None and parsed.utcoffset().total_seconds() == 0,
             f"{label}_must_be_utc")
    return parsed.astimezone(timezone.utc)


def _amount_units(value):
    # Tuple arithmetic avoids both float parsing and ambient Decimal rounding.
    _require(type(value) in (int, Decimal), "activity_amount_not_json_number")
    amount = Decimal(value)
    _require(amount.is_finite() and amount > 0, "activity_amount_not_positive_finite")
    sign, digits, exponent = amount.as_tuple()
    _require(not sign and len(digits) <= 78 and -100 <= exponent <= 100,
             "activity_amount_out_of_range")
    coefficient = int("".join(str(digit) for digit in digits))
    shift = exponent + 6
    if shift >= 0:
        _require(len(digits) + shift <= 78, "activity_amount_out_of_range")
        units = coefficient * 10 ** shift
    else:
        units, remainder = divmod(coefficient, 10 ** -shift)
        _require(remainder == 0, "activity_amount_not_exact_micro_units")
    _require(0 < units < 2 ** 256, "activity_amount_out_of_range")
    return units


def _amount_text(units):
    return f"{units // 1_000_000}.{units % 1_000_000:06d}"


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "capture_duplicate_json_key")
        result[key] = value
    return result


def _parse_integer(value):
    _require(len(value) <= 80, "capture_integer_too_large")
    return int(value)


def _reject_constant(value):
    raise _Invalid("capture_nonfinite_json_number")


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _same_json_value(left, right):
    """JSON booleans/numbers are distinct even though Python equates False/0."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _same_json_value(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _same_json_value(a, b) for a, b in zip(left, right)
        )
    return left == right


def _request_text(request):
    _require(isinstance(request, dict), "capture_request_invalid")
    if request.get("method") == "GET":
        _require(set(request) == {"method", "url"} and isinstance(request["url"], str)
                 and len(request["url"]) <= 1_500, "capture_request_invalid")
    else:
        _require(set(request) == {"jsonrpc", "id", "method", "params"}
                 and request["jsonrpc"] == "2.0" and isinstance(request["method"], str)
                 and len(request["method"]) <= 40 and type(request["id"]) is int
                 and 0 <= request["id"] <= 2 ** 31 - 1 and isinstance(request["params"], list)
                 and len(request["params"]) <= 2 and all(
                     type(value) is bool or isinstance(value, str) and len(value) <= 80
                     for value in request["params"]
                 ), "capture_request_invalid")
    return _canonical(request)


def _capture(capture, as_of, provenance):
    _require(isinstance(capture, dict) and set(capture) == {
        "source_id", "request", "observed_at_utc", "http_status",
        "raw_response", "raw_response_sha256",
    }, "capture_envelope_invalid")
    source = capture["source_id"]
    _require(isinstance(source, str) and _SOURCE.fullmatch(source), "capture_source_id_invalid")
    observed = _time(capture["observed_at_utc"], "capture_observed_at")
    _require(observed <= as_of, "capture_observed_after_as_of")
    _require(type(capture["http_status"]) is int and capture["http_status"] == 200,
             "capture_http_status_not_success")
    raw = capture["raw_response"]
    _require(isinstance(raw, str) and len(raw) <= MAX_CAPTURE_BYTES, "capture_size_exceeded")
    raw_bytes = raw.encode("utf-8")
    _require(len(raw_bytes) <= MAX_CAPTURE_BYTES, "capture_size_exceeded")
    digest = hashlib.sha256(raw_bytes).hexdigest()
    supplied = capture["raw_response_sha256"]
    _require(isinstance(supplied, str) and _SHA.fullmatch(supplied)
             and digest == supplied.lower(), "capture_response_hash_mismatch")
    request = capture["request"]
    request_text = _request_text(request)
    receipt = {
        "source_id": source, "request": json.loads(request_text),
        "request_sha256": hashlib.sha256(request_text.encode("utf-8")).hexdigest(),
        "response_sha256": digest, "observed_at_utc": observed.isoformat(),
    }
    capture_id = hashlib.sha256(_canonical(receipt).encode("utf-8")).hexdigest()
    provenance[capture_id] = receipt
    try:
        payload = json.loads(raw, parse_float=Decimal, parse_int=_parse_integer,
                             parse_constant=_reject_constant, object_pairs_hook=_pairs)
    except (ValueError, DecimalException, RecursionError) as exc:
        if isinstance(exc, _Invalid):
            raise
        raise _Invalid("capture_json_invalid") from exc
    return payload, request, observed, capture_id


def _activity_rows(captures, scope, times, provenance):
    rows, duplicates, count = {}, 0, 0
    for capture in captures:
        payload, request, observed, capture_id = _capture(capture, times["as_of_utc"], provenance)
        _require(set(request) == {"method", "url"} and request["method"] == "GET"
                 and isinstance(request["url"], str), "activity_request_invalid")
        parsed = urlsplit(request["url"])
        _require(parsed.scheme == "https" and parsed.netloc == "data-api.polymarket.com"
                 and parsed.path == "/activity" and not parsed.fragment, "activity_endpoint_invalid")
        pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
        query = dict(pairs)
        _require(len(query) == len(pairs) and set(query) == {
            "user", "start", "end", "limit", "offset", "sortBy", "sortDirection",
            "excludeDepositsWithdrawals",
        }, "activity_query_shape_invalid")
        _require(query["user"].lower() == scope["maker_address"]
                 and query["start"] == str(int(times["activity_start_utc"].timestamp()))
                 and query["end"] == str(int(times["activity_end_utc"].timestamp()))
                 and query["sortBy"] == "TIMESTAMP" and query["sortDirection"] == "ASC"
                 and query["excludeDepositsWithdrawals"] == "false", "activity_query_scope_mismatch")
        _require(query["limit"].isdigit() and 1 <= int(query["limit"]) <= 500
                 and query["offset"].isdigit() and 0 <= int(query["offset"]) <= 5_000,
                 "activity_pagination_invalid")
        _require(observed >= times["activity_end_utc"], "activity_capture_precedes_window_end")
        _require(isinstance(payload, list) and len(payload) <= int(query["limit"]),
                 "activity_response_shape_invalid")
        count += len(payload)
        _require(count <= MAX_ACTIVITY_ROWS, "activity_row_limit_exceeded")
        for row in payload:
            _require(isinstance(row, dict), "activity_row_invalid")
            if row.get("type") not in ACTIVITY_TYPES:
                continue
            account = _hex(row.get("proxyWallet"), 20, "activity_account")
            _require(account == scope["maker_address"], "activity_account_mismatch")
            tx = _hex(row.get("transactionHash"), 32, "activity_transaction")
            condition = _hex(row.get("conditionId"), 32, "activity_condition")
            _require(condition == scope["condition_id"], "activity_condition_mismatch", unresolved=True)
            timestamp = row.get("timestamp")
            _require(type(timestamp) is int and times["activity_start_utc"].timestamp() <= timestamp
                     <= times["activity_end_utc"].timestamp(), "activity_timestamp_outside_window")
            normalized = {
                "transaction_hash": tx, "maker_address": account, "condition_id": condition,
                "venue_activity_type": row["type"], "activity_timestamp": timestamp,
                "amount_micro_units": _amount_units(row.get("usdcSize")),
            }
            key = hashlib.sha256(_canonical(normalized).encode("utf-8")).hexdigest()
            if key in rows:
                duplicates += 1
                rows[key]["activity_capture_ids"].add(capture_id)
            else:
                rows[key] = {**normalized, "activity_capture_ids": {capture_id}}
    return rows, duplicates


def _rpc_results(captures, as_of, provenance):
    results, duplicates = {}, 0
    for capture in captures:
        payload, request, observed, capture_id = _capture(capture, as_of, provenance)
        _require(set(request) == {"jsonrpc", "id", "method", "params"}
                 and request["jsonrpc"] == "2.0" and request["method"] in RPC_METHODS
                 and type(request["id"]) is int and 0 <= request["id"] <= 2 ** 31 - 1
                 and isinstance(request["params"], list), "rpc_request_invalid")
        method, params = request["method"], request["params"]
        if method == "eth_chainId":
            _require(params == [], "rpc_chain_request_invalid")
        elif method == "eth_getTransactionReceipt":
            _require(len(params) == 1, "rpc_receipt_request_invalid")
            params = [_hex(params[0], 32, "rpc_requested_transaction")]
        else:
            _require(len(params) == 2 and params[1] is False, "rpc_block_request_invalid")
            if params[0] != "finalized":
                params = [hex(_quantity(params[0], "rpc_requested_block")), False]
        _require(isinstance(payload, dict) and set(payload) == {"jsonrpc", "id", "result"}
                 and payload["jsonrpc"] == "2.0" and type(payload["id"]) is int
                 and payload["id"] == request["id"], "rpc_response_envelope_invalid")
        result = payload["result"]
        if method == "eth_chainId":
            _require(_quantity(result, "rpc_chain_id") == 137, "rpc_chain_id_mismatch")
        else:
            _require(isinstance(result, dict), "rpc_result_missing", unresolved=True)
        key = (capture["source_id"], method, _canonical(params))
        if key in results:
            _require(_same_json_value(result, results[key]["result"]),
                     "rpc_conflicting_capture", unresolved=True)
            results[key]["capture_ids"].add(capture_id)
            # Keep the oldest time: a later duplicate cannot improve ordering proof.
            results[key]["observed"] = min(observed, results[key]["observed"])
            duplicates += 1
        else:
            results[key] = {"result": result, "observed": observed, "capture_ids": {capture_id}}
    return results, duplicates


def _rpc_get(results, source, method, params):
    record = results.get((source, method, _canonical(params)))
    _require(record is not None, "required_rpc_capture_missing", unresolved=True)
    return record


def _confirmed_transfers(tx, results, scope, times):
    matches = [(key[0], record) for key, record in results.items()
               if key[1] == "eth_getTransactionReceipt" and key[2] == _canonical([tx])]
    _require(len(matches) == 1, "transaction_receipt_missing_or_ambiguous", unresolved=True)
    source, receipt_capture = matches[0]
    chain = _rpc_get(results, source, "eth_chainId", [])
    receipt = receipt_capture["result"]
    _require(_hex(receipt.get("transactionHash"), 32, "receipt_transaction") == tx,
             "receipt_transaction_mismatch")
    _require(_quantity(receipt.get("status"), "receipt_status") == 1,
             "receipt_not_successful", unresolved=True)
    number = _quantity(receipt.get("blockNumber"), "receipt_block_number")
    block_hash = _hex(receipt.get("blockHash"), 32, "receipt_block_hash")
    transaction_index = _quantity(receipt.get("transactionIndex"), "receipt_transaction_index")
    block_capture = _rpc_get(results, source, "eth_getBlockByNumber", [hex(number), False])
    final_capture = _rpc_get(results, source, "eth_getBlockByNumber", ["finalized", False])
    block, final = block_capture["result"], final_capture["result"]
    _require(_quantity(block.get("number"), "canonical_block_number") == number
             and _hex(block.get("hash"), 32, "canonical_block_hash") == block_hash,
             "receipt_not_in_canonical_block", unresolved=True)
    final_number = _quantity(final.get("number"), "finalized_block_number")
    final_hash = _hex(final.get("hash"), 32, "finalized_block_hash")
    _require(final_number >= number and (final_number != number or final_hash == block_hash),
             "receipt_block_not_finalized", unresolved=True)
    _require(block_capture["observed"] >= final_capture["observed"],
             "canonical_block_capture_precedes_finality", unresolved=True)
    block_time = _quantity(block.get("timestamp"), "canonical_block_timestamp")
    final_time = _quantity(final.get("timestamp"), "finalized_block_timestamp")
    _require(block_time <= final_time <= final_capture["observed"].timestamp()
             and block_time <= receipt_capture["observed"].timestamp(), "rpc_block_time_invalid")
    _require(times["activity_start_utc"].timestamp() <= block_time
             <= times["activity_end_utc"].timestamp(), "transfer_block_outside_window", unresolved=True)
    transactions = block.get("transactions")
    _require(isinstance(transactions, list) and len(transactions) <= 5_000
             and transaction_index < len(transactions), "canonical_block_transactions_invalid")
    transactions = [_hex(value, 32, "canonical_block_transaction") for value in transactions]
    _require(len(set(transactions)) == len(transactions) and transactions[transaction_index] == tx,
             "receipt_transaction_not_in_canonical_block", unresolved=True)
    logs = receipt.get("logs")
    _require(isinstance(logs, list) and len(logs) <= MAX_RECEIPT_LOGS, "receipt_logs_invalid")
    transfers, seen_logs = [], set()
    for log in logs:
        _require(isinstance(log, dict), "receipt_log_invalid")
        index = _quantity(log.get("logIndex"), "receipt_log_index")
        _require(index not in seen_logs, "receipt_duplicate_log_index", unresolved=True)
        seen_logs.add(index)
        _require(log.get("removed") is False
                 and _hex(log.get("transactionHash"), 32, "log_transaction") == tx
                 and _hex(log.get("blockHash"), 32, "log_block_hash") == block_hash
                 and _quantity(log.get("blockNumber"), "log_block_number") == number
                 and _quantity(log.get("transactionIndex"), "log_transaction_index") == transaction_index,
                 "receipt_log_context_mismatch", unresolved=True)
        address = _hex(log.get("address"), 20, "log_address")
        topics = log.get("topics")
        _require(isinstance(topics, list) and len(topics) <= 4, "receipt_log_topics_invalid")
        topics = [_hex(value, 32, "log_topic") for value in topics]
        if address != scope["asset_address"] or not topics or topics[0] != TRANSFER_TOPIC:
            continue
        _require(len(topics) == 3 and all(topic[2:26] == "0" * 24 for topic in topics[1:]),
                 "pusd_transfer_topics_invalid")
        sender, recipient = ("0x" + topic[-40:] for topic in topics[1:])
        amount = int(_hex(log.get("data"), 32, "pusd_transfer_amount"), 16)
        if recipient == scope["maker_address"] and sender != recipient and amount > 0:
            transfers.append({
                "credit_id": f"137:{tx}:{index}", "transaction_hash": tx,
                "log_index": index, "block_number": number, "block_hash": block_hash,
                "block_timestamp": block_time, "sender": sender, "recipient": recipient,
                "amount_micro_units": amount, "amount": _amount_text(amount),
                "finalized_block_number": final_number, "finalized_block_hash": final_hash,
            })
    capture_ids = set().union(*(record["capture_ids"] for record in (
        chain, receipt_capture, block_capture, final_capture,
    )))
    return transfers, sorted(capture_ids)


def bridge_activity_credits(evidence):
    """Join only unique exact credits; all observations remain caller supplied.

    Input/output are in-memory values, not persisted artifact schemas. Empty or
    incomplete captures never establish zero payments. No input is modified.
    """
    output = {
        "status": "INVALID", "credits": [], "matched_transfer_total_micro_units": None,
        "matched_transfer_total": None, "blockers": [], "provenance": {},
        "duplicate_activity_count": 0, "duplicate_rpc_capture_count": 0,
        "evidence_origin": "CALLER_SUPPLIED_RAW_CAPTURES", "label_linkage": "DERIVED",
        "network_reads_performed": False, "source_authenticity_verified": False,
        "accrual_linkage_verified": False, "account_cash_completeness_verified": False,
        "economic_pnl_verified": False, "live_authority": False,
    }
    provenance = {}
    try:
        _require(isinstance(evidence, dict) and set(evidence) == {
            "scope", "activity_captures", "rpc_captures",
        }, "evidence_shape_invalid")
        supplied_scope = evidence["scope"]
        _require(isinstance(supplied_scope, dict) and set(supplied_scope) == {
            "maker_address", "condition_id", "chain_id", "asset_address", "asset_decimals",
            "activity_start_utc", "activity_end_utc", "as_of_utc",
        }, "scope_shape_invalid")
        scope = dict(supplied_scope)
        scope["maker_address"] = _hex(scope["maker_address"], 20, "scope_account")
        scope["condition_id"] = _hex(scope["condition_id"], 32, "scope_condition")
        scope["asset_address"] = _hex(scope["asset_address"], 20, "scope_asset")
        _require(type(scope["chain_id"]) is int and scope["chain_id"] == 137
                 and type(scope["asset_decimals"]) is int and scope["asset_decimals"] == 6
                 and scope["asset_address"] == PUSD_COLLATERAL_PROXY_ADDRESS,
                 "scope_native_asset_mismatch")
        times = {key: _time(scope[key], key) for key in (
            "activity_start_utc", "activity_end_utc", "as_of_utc",
        )}
        _require(times["activity_start_utc"] < times["activity_end_utc"] <= times["as_of_utc"]
                 and all(times[key].microsecond == 0 for key in times if key != "as_of_utc"),
                 "scope_time_window_invalid")
        output["scope"] = {**scope, **{key: value.isoformat() for key, value in times.items()}}
        activity, rpc = evidence["activity_captures"], evidence["rpc_captures"]
        _require(isinstance(activity, list) and isinstance(rpc, list)
                 and 0 < len(activity) <= MAX_CAPTURES and len(rpc) <= MAX_CAPTURES,
                 "capture_count_invalid")
        captures = activity + rpc
        _require(all(isinstance(row, dict) and isinstance(row.get("raw_response"), str)
                     and len(row["raw_response"]) <= MAX_CAPTURE_BYTES for row in captures),
                 "capture_size_exceeded")
        _require(sum(len(row["raw_response"]) for row in captures) <= MAX_TOTAL_BYTES,
                 "capture_total_size_exceeded")
        _require(sum(len(row["raw_response"].encode("utf-8")) for row in captures) <= MAX_TOTAL_BYTES,
                 "capture_total_size_exceeded")
        rows, output["duplicate_activity_count"] = _activity_rows(activity, scope, times, provenance)
        results, output["duplicate_rpc_capture_count"] = _rpc_results(rpc, times["as_of_utc"], provenance)
        credits, claimed, cache = [], set(), {}
        for key, row in sorted(rows.items()):
            tx = row["transaction_hash"]
            if tx not in cache:
                cache[tx] = _confirmed_transfers(tx, results, scope, times)
            transfers, rpc_capture_ids = cache[tx]
            matches = [transfer for transfer in transfers
                       if transfer["amount_micro_units"] == row["amount_micro_units"]]
            _require(len(matches) == 1, "activity_transfer_missing_or_ambiguous", unresolved=True)
            transfer = matches[0]
            _require(transfer["credit_id"] not in claimed, "transfer_credit_claimed_twice", unresolved=True)
            claimed.add(transfer["credit_id"])
            credits.append({
                **transfer, "activity_id": f"derived:{key}", "label_linkage": "DERIVED",
                "venue_activity_type": row["venue_activity_type"], "condition_id": row["condition_id"],
                "activity_timestamp": row["activity_timestamp"],
                "confirmation_basis": "SUPPLIED_SUCCESSFUL_RECEIPT_CANONICAL_BLOCK_AND_FINALIZED_TIP",
                "activity_capture_ids": sorted(row["activity_capture_ids"]),
                "rpc_capture_ids": rpc_capture_ids,
            })
        output["status"] = "JOINED" if credits else "EMPTY_SUBSET"
        output["credits"] = sorted(credits, key=lambda row: row["credit_id"])
        if credits:
            total = sum(row["amount_micro_units"] for row in credits)
            output["matched_transfer_total_micro_units"] = total
            output["matched_transfer_total"] = _amount_text(total)
    except (ValueError, DecimalException, TypeError, OverflowError, RecursionError, UnicodeError) as exc:
        output["status"] = "UNRESOLVED" if isinstance(exc, _Unresolved) else "INVALID"
        output["blockers"] = [str(exc) if isinstance(exc, _Invalid) else "evidence_encoding_invalid"]
    output["provenance"] = dict(sorted(provenance.items()))
    return output
