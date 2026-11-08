"""Read-only native-collateral attestations; Data API USD labels are not FX.

ERC-20 Transfer: https://eips.ethereum.org/EIPS/eip-20
Receipt: https://ethereum.org/en/developers/docs/apis/json-rpc/#eth_gettransactionreceipt
Only chain identity, token decimals, receipts and historical CTF views can be requested.
No transaction submission, signing, allowance or wallet mutation exists here.
"""
from collections import defaultdict
import json
import re
import time
from urllib.request import Request
from urllib.error import HTTPError

from weather.market.lfc_recording_io import retained, response_bytes, strict_json, PublicReadFailure
from weather.market.mm_stage2_hold import digest
from weather.market.wallet_reader_transport import direct_opener


TRANSFER = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'
MAX_BYTES = 2_000_000
MAX_NEW_RECEIPTS = 200
MAX_NEW_VIEWS = 100


def rpc_read(method, params, *, opener=None):
    from weather.market.re1_transport import RPC
    from weather.market.lfc_capital import ASSET
    from weather.operations.live_path_security import assert_no_ambient_proxy_configuration
    from weather.market.lfc_redemption_native import permitted_call
    if not isinstance(params, list):
        raise ValueError('capital_rpc_method_refused')
    allowed = (method == 'eth_chainId' and params == [] or
               method == 'eth_call' and params == [{'to': ASSET, 'data': '0x313ce567'}, 'latest'] or
               method == 'eth_call' and permitted_call(params) or
               method == 'eth_getTransactionReceipt' and len(params) == 1 and
               isinstance(params[0], str) and re.fullmatch('0x[0-9a-fA-F]{64}', params[0]))
    if not allowed:
        raise ValueError('capital_rpc_method_refused')
    assert_no_ambient_proxy_configuration()
    raw = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}, separators=(',', ':')).encode()
    request = Request(RPC, data=raw, method='POST', headers={'Content-Type': 'application/json',
                      'Accept': 'application/json', 'User-Agent': 'weather-lfc-capital/1'})
    try:
        response = (opener or direct_opener().open)(request, timeout=5)
    except HTTPError as exc:
        try:
            body = exc.read(MAX_BYTES + 1)
            raise PublicReadFailure('capital_rpc_response_refused', status=exc.code,
                                    raw=body[:MAX_BYTES], truncated=len(body) > MAX_BYTES) from None
        finally:
            exc.close()
    try:
        body = response.read(MAX_BYTES + 1)
        if response.status != 200 or response.geturl() != RPC or len(body) > MAX_BYTES:
            raise PublicReadFailure('capital_rpc_response_refused', status=response.status,
                                    raw=body[:MAX_BYTES], truncated=len(body) > MAX_BYTES)
        packet = retained(body)
        result(packet)
        return packet
    finally:
        response.close()


def result(packet):
    value = strict_json(response_bytes(packet))
    if (not isinstance(value, dict) or value.get('jsonrpc') != '2.0' or type(value.get('id')) is not int or
            value['id'] != 1 or 'error' in value or 'result' not in value):
        raise ValueError('capital_rpc_envelope')
    return value['result']


def hex_number(value):
    if not isinstance(value, str) or re.fullmatch('0x[0-9a-fA-F]+', value) is None:
        raise ValueError('capital_rpc_quantity')
    return int(value, 16)


def validate_asset(proof):
    from weather.market.lfc_capital import ASSET
    if (proof.get('asset') != ASSET or hex_number(result(proof['chain'])) != 137 or
            hex_number(result(proof['decimals'])) != 6):
        raise ValueError('capital_native_asset_identity')
    return proof


def collect(packet, *, ledger, rpc=rpc_read, sleep=time.sleep):
    """Retain raw receipts, reusing ledger-anchored historical observations."""
    from weather.market.lfc_capital import ASSET
    cache, cached_views = {}, {}
    for event in ledger.capital_rows:
        proof = event.get('proof') if event['event'] == 'capital_native_group' else event.get('native_evidence')
        if proof is not None and proof.get('receipt') is not None and result(proof['receipt']) is not None:
            cache[proof['transaction_hash']] = proof['receipt']
            cached_views[proof['transaction_hash']] = proof.get('ctf_views', {})
    chain = rpc('eth_chainId', [])
    sleep(.5)
    decimals = rpc('eth_call', [{'to': ASSET, 'data': '0x313ce567'}, 'latest'])
    sleep(.5)
    metadata = {'asset': ASSET, 'chain': chain, 'decimals': decimals}
    validate_asset(metadata)
    grouped = defaultdict(list)
    for row in packet['rows']:
        grouped[str(row['transaction_hash']).lower()].append(row)
    if len(set(grouped) - set(cache)) > MAX_NEW_RECEIPTS:
        raise ValueError('capital_native_receipt_budget')
    proofs, byte_count, new_views = {}, 0, 0
    known_groups = {row['proof_sha256'] for row in ledger.capital_rows if row['event'] == 'capital_native_group'}
    for tx, rows in grouped.items():
        receipt, failure, failed_response = cache.get(tx), None, None
        if receipt is None:
            try:
                receipt = rpc('eth_getTransactionReceipt', [tx])
            except Exception as exc:
                failure = type(exc).__name__
                if isinstance(getattr(exc, 'raw', None), bytes):
                    failed_response = {**retained(exc.raw), 'status': getattr(exc, 'status', None),
                                       'truncated': getattr(exc, 'truncated', False)}
            sleep(.5)
        if receipt is not None and tx not in cache:
            byte_count += len(response_bytes(receipt))
            if byte_count > 16_000_000:
                receipt, failure = None, 'capital_native_read_budget'
        proof = {'transaction_hash': tx, 'rows': rows, 'rows_sha256': digest(rows),
                 'receipt': receipt, 'failure_type': failure,
                 **({} if failed_response is None else {'failed_response': failed_response})}
        if receipt is not None and result(receipt) is not None and any(r['type'] == 'REDEEM' for r in rows):
            from weather.market.lfc_redemption_native import CTF, ctf_requests
            views = dict(cached_views.get(tx, {}))
            try:
                for data in ctf_requests(result(receipt), makers={str(r['proxy_wallet']).lower() for r in rows if r['type'] == 'REDEEM'}):
                    if data not in views:
                        if new_views >= MAX_NEW_VIEWS:
                            raise ValueError('capital_native_view_budget')
                        new_views += 1
                        try:
                            views[data] = rpc('eth_call', [{'to': CTF, 'data': data}, result(receipt)['blockNumber']])
                        finally:
                            sleep(.5)
                proof['ctf_views'] = views
            except Exception as exc:
                proof['redemption_failure_type'] = type(exc).__name__
        sha = digest(proof)
        if sha not in known_groups:
            ledger.record('capital_native_group', proof=proof, proof_sha256=sha)
            known_groups.add(sha)
        # The receipt bytes exist once in the ledger, not once per cash row or
        # in every later account/closure receipt. This bounds memory and avoids
        # amplifying a batched venue transaction into many copies.
        proofs[tx] = {'native_group_sha256': sha}
    return {**packet, 'native_asset_proof': metadata, 'native_receipts': proofs}


def resolve(proof, ledger):
    if set(proof) == {'native_group_sha256'}:
        from weather.market.lfc_capital import CapitalBook
        proof = CapitalBook(ledger).native_groups.get(proof['native_group_sha256'])
        if proof is None:
            raise ValueError('capital_native_group_missing')
    return proof


def validate_packet(packet, *, ledger=None):
    validate_asset(packet['native_asset_proof'])
    grouped = defaultdict(list)
    for source in packet['rows']:
        grouped[str(source['transaction_hash']).lower()].append(source)
    if set(grouped) != set(packet['native_receipts']):
        raise ValueError('capital_native_receipt_coverage')
    for tx, rows in grouped.items():
        proof = resolve(packet['native_receipts'][tx], ledger)
        if proof['rows'] != rows or proof['rows_sha256'] != digest(rows) or proof['transaction_hash'] != tx:
            raise ValueError('capital_native_batch_scope')
        for source in rows:
            cash_native(source, proof)


def evidence_for(packet, source, *, ledger=None):
    tx = str(source['transaction_hash']).lower()
    proof = resolve(packet['native_receipts'][tx], ledger)
    if proof['rows_sha256'] != digest(proof['rows']) or source not in proof['rows']:
        raise ValueError('capital_native_row_scope')
    return proof


def cash_native(source, proof):
    """Allocate only chain-proved native units, never a USD conversion.

    A lone incoming row must match the native transfer exactly. Multiple
    incoming rows for the maker are UNKNOWN: a total ERC-20 transfer cannot
    prove which condition earned it, even when the Data API labels sum exactly.
    A USD label is never converted to collateral. An unallocated payout stays
    unknown and its full basis stays charged. A lone outgoing row conservatively
    charges the transaction's entire native debit.
    """
    from weather.market.lfc_capital import ASSET, native
    if (proof.get('rows_sha256') != digest(proof['rows']) or source not in proof['rows'] or
            str(source['transaction_hash']).lower() != proof['transaction_hash']):
        raise ValueError('capital_native_row_scope')
    if proof.get('receipt') is None:
        return None
    receipt = result(proof['receipt'])
    if receipt is None:
        return None
    if (not isinstance(receipt, dict) or str(receipt.get('transactionHash', '')).lower() != proof['transaction_hash'] or
            hex_number(receipt.get('status')) != 1 or not isinstance(receipt.get('logs'), list) or
            re.fullmatch('0x[0-9a-fA-F]{64}', str(receipt.get('blockHash'))) is None):
        raise ValueError('capital_native_receipt_scope')
    block = hex_number(receipt.get('blockNumber'))
    maker = str(source['proxy_wallet']).lower()
    total, indices = {'IN': 0, 'OUT': 0}, set()
    for ordinal, log in enumerate(receipt['logs']):
        if not isinstance(log, dict):
            raise ValueError('capital_native_transfer_shape')
        if str(log.get('address', '')).lower() != ASSET:
            continue
        topics = log.get('topics')
        if not isinstance(topics, list) or not topics:
            raise ValueError('capital_native_transfer_shape')
        if str(topics[0]).lower() != TRANSFER:
            continue
        if (len(topics) != 3 or any(re.fullmatch('0x[0-9a-fA-F]{64}', str(t)) is None for t in topics) or
                any(t[2:26] != '0' * 24 for t in topics[1:]) or
                re.fullmatch('0x[0-9a-fA-F]{64}', str(log.get('data'))) is None or
                'removed' in log and log['removed'] is not False or
                str(log.get('transactionHash', '')).lower() != proof['transaction_hash'] or
                'blockHash' in log and str(log['blockHash']).lower() != receipt['blockHash'].lower() or
                'blockNumber' in log and hex_number(log['blockNumber']) != block):
            raise ValueError('capital_native_transfer_shape')
        index = ('chain', hex_number(log['logIndex'])) if 'logIndex' in log else ('receipt', ordinal)
        if index in indices:
            raise ValueError('capital_native_duplicate_log')
        indices.add(index)
        sender, receiver = ('0x' + t[-40:].lower() for t in topics[1:])
        value = hex_number(log['data'])
        if receiver == maker and sender != maker:
            total['IN'] += value
        if sender == maker and receiver != maker:
            total['OUT'] += value
    def direction(row):
        if row['type'] == 'TIP':
            if row.get('side') not in ('IN', 'OUT'):
                raise ValueError('capital_tip_direction')
            return row['side']
        return 'OUT' if row['type'] == 'WITHDRAWAL' else 'IN'
    side = direction(source)
    rows = [row for row in proof['rows'] if str(row['proxy_wallet']).lower() == maker and direction(row) == side]
    if source['type'] == 'REDEEM':
        from weather.market.lfc_redemption_native import positions, REDEEM, POSITION
        bundle = positions(source, proof)
        if bundle is not None and all(row['type'] == 'REDEEM' for row in rows):
            return sum(p['cash_native'] for p in bundle['positions'])
        # A partial chain redemption is not a single-position proof merely
        # because the API collapsed it to one row or supplied outcome 999.
        if any(log.get('topics', [None])[0] in (REDEEM, POSITION) for log in receipt['logs']):
            return None
    if side == 'IN' and len(rows) > 1:
        return None
    if len(rows) == 1 and side == 'OUT':
        return total[side]
    if total[side] == 0:
        return 0
    if any(row.get('usdc_size') is None for row in rows):
        return None
    try:
        amounts = [native(row['usdc_size']) for row in rows]
    except ValueError:
        return None
    return native(source['usdc_size']) if sum(amounts) == total[side] else None
