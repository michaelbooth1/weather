"""Position-scoped redemption proofs, derived from public contract events.

Sources: Polymarket/polymarket-v2-external (BaseModule, AutoRedeemer),
gnosis/conditional-tokens-contracts/ConditionalTokens.sol, and ERC-1155.
Only mined receipts and historical, allowlisted CTF views are consumed.
An incomplete proof returns no principal; Data API outcome labels are unused.
"""
from decimal import Decimal
import re

from eth_abi import decode, encode
from eth_utils import keccak

CTF = '0x4d97dcd97ec945f40cf65f87097ace5ea0476045'
PM = '0x006f54f7f9a22e0000cc2ab60031000000ae9fef'
AUTO = '0xa1200000d0002264c9a1698e001292d00e1b00af'
MODULES = {'0x1000008dd9001b968442c1000017eae6e0da00ba',
           '0x200000900045e3b6259600682756002200028933',
           '0x30000034706c7d8e12009dab006be20000c031a8'}
ZERO = '0x' + '0' * 40


def topic(signature):
    return '0x' + keccak(text=signature).hex()


SINGLE = topic('TransferSingle(address,address,address,uint256,uint256)')
BATCH = topic('TransferBatch(address,address,address,uint256[],uint256[])')
REDEEM = topic('PayoutRedemption(address,address,bytes32,bytes32,uint256[],uint256)')
POSITION = topic('PositionRedeemed(address,uint256,address,uint256,uint256)')
AUTO_POSITION = topic('Redemption(address,uint256,uint256)')
AUTO_BINARY = topic('BinaryRedemption(address,bytes32,uint256)')
AUTO_NEG = topic('NegRiskRedemption(address,bytes32,uint256)')


def call_data(signature, types, args):
    return '0x' + (keccak(text=signature)[:4] + encode(types, args)).hex()


def ctf_calls(cid):
    raw = bytes.fromhex(cid[2:])
    return [call_data('payoutDenominator(bytes32)', ['bytes32'], [raw]),
            *[call_data('payoutNumerators(bytes32,uint256)', ['bytes32', 'uint256'], [raw, i]) for i in (0, 1)],
            *[call_data('getCollectionId(bytes32,bytes32,uint256)', ['bytes32', 'bytes32', 'uint256'],
                        [bytes(32), raw, i]) for i in (1, 2)]]


def permitted_call(params):
    if (not isinstance(params, list) or len(params) != 2 or not isinstance(params[0], dict) or
            set(params[0]) != {'to', 'data'} or params[0]['to'] != CTF or
            not isinstance(params[1], str) or re.fullmatch('0x[0-9a-fA-F]+', params[1]) is None):
        return False
    data = params[0]['data']
    if not isinstance(data, str) or re.fullmatch('0x[0-9a-fA-F]+', data) is None:
        return False
    if len(data) == 74 and data[:10] == call_data('payoutDenominator(bytes32)', ['bytes32'], [bytes(32)])[:10]:
        return True
    if len(data) == 138 and data[:10] == call_data('payoutNumerators(bytes32,uint256)', ['bytes32', 'uint256'], [bytes(32), 0])[:10]:
        return int(data[-64:], 16) in (0, 1)
    return (len(data) == 202 and data[:10] == call_data('getCollectionId(bytes32,bytes32,uint256)',
            ['bytes32', 'bytes32', 'uint256'], [bytes(32), bytes(32), 1])[:10] and
            int(data[10:74], 16) == 0 and int(data[-64:], 16) in (1, 2))


def unpack(log, count, types):
    topics = log['topics']
    if len(topics) != count or any(re.fullmatch('0x[0-9a-fA-F]{64}', str(t)) is None for t in topics):
        raise ValueError('redemption_event_shape')
    raw = bytes.fromhex(log['data'][2:])
    values = decode(types, raw, strict=True)
    if encode(types, values) != raw:
        raise ValueError('redemption_event_encoding')
    return values


def address(value):
    if value[2:26] != '0' * 24:
        raise ValueError('redemption_event_address')
    return '0x' + value[-40:].lower()


def ctf_requests(receipt):
    requests = set()
    for log in receipt.get('logs', []):
        if str(log.get('address', '')).lower() == CTF and log.get('topics', [None])[0] == REDEEM:
            cid, _, _ = unpack(log, 4, ['bytes32', 'uint256[]', 'uint256'])
            for data in ctf_calls('0x' + cid.hex()):
                requests.add(data)
    if len(requests) > 100:
        raise ValueError('redemption_view_budget')
    return sorted(requests)


def positions(source, proof):
    """Return a complete maker/transaction bundle, or None when unproved.

    All holder quantities and payouts come from chain events. One API row can
    represent both tokens; many API rows can represent the same transaction.
    The caller deduplicates that bundle by transaction hash.
    """
    from weather.market.lfc_capital_native import result, TRANSFER
    from weather.market.lfc_capital import ASSET
    if proof.get('receipt') is None or result(proof['receipt']) is None:
        return None
    receipt = result(proof['receipt'])
    maker, tx = source['proxy_wallet'].lower(), proof['transaction_hash']
    burns, transfers, modules, auto, ctf, incoming, outgoing = {}, {}, [], [], [], 0, 0
    try:
        indices = set()
        for ordinal, log in enumerate(receipt['logs']):
            contract, topics = str(log.get('address', '')).lower(), log.get('topics', [])
            if contract not in MODULES | {CTF, PM, AUTO, ASSET} or not topics:
                continue
            if (log.get('removed', False) is not False or log.get('transactionHash', '').lower() != tx or
                    log.get('blockHash', receipt['blockHash']).lower() != receipt['blockHash'].lower() or
                    int(log.get('blockNumber', receipt['blockNumber']), 16) != int(receipt['blockNumber'], 16)):
                raise ValueError('redemption_log_scope')
            index = int(log.get('logIndex', hex(ordinal)), 16)
            if index in indices:
                raise ValueError('redemption_duplicate_log')
            indices.add(index)
            event = topics[0].lower()
            if contract == ASSET and event == TRANSFER:
                (amount,) = unpack(log, 3, ['uint256'])
                sender, recipient = address(topics[1]), address(topics[2])
                if recipient == maker and sender != maker:
                    incoming += amount
                if sender == maker and recipient != maker:
                    outgoing += amount
            elif contract in (CTF, PM) and event in (SINGLE, BATCH):
                sender, recipient = address(topics[2]), address(topics[3])
                if event == SINGLE:
                    token, amount = unpack(log, 4, ['uint256', 'uint256'])
                    pairs = [(token, amount)]
                else:
                    ids, amounts = unpack(log, 4, ['uint256[]', 'uint256[]'])
                    if len(ids) != len(amounts) or len(ids) > 256:
                        raise ValueError('redemption_batch_shape')
                    pairs = list(zip(ids, amounts))
                for token, amount in pairs:
                    key = (contract, sender, recipient, token)
                    transfers[key] = transfers.get(key, 0) + amount
                    if recipient == ZERO:
                        burns[(contract, token)] = burns.get((contract, token), 0) + amount
            elif contract in MODULES and event == POSITION:
                amount, payout = unpack(log, 4, ['uint256', 'uint256'])
                modules.append((contract, address(topics[1]), int(topics[2], 16), address(topics[3]), amount, payout))
            elif contract == AUTO and event == AUTO_POSITION:
                (payout,) = unpack(log, 3, ['uint256'])
                if address(topics[1]) == maker:
                    auto.append((int(topics[2], 16), payout))
            elif contract == CTF and event == REDEEM:
                cid, slots, payout = unpack(log, 4, ['bytes32', 'uint256[]', 'uint256'])
                if int(topics[3], 16) == 0 and set(slots) == {1, 2} and len(slots) == 2:
                    ctf.append((address(topics[1]), address(topics[2]), '0x' + cid.hex(), payout))
        found = []
        for contract, initiator, token, recipient, amount, payout in modules:
            if recipient != maker and not (initiator == AUTO and recipient == AUTO and (token, payout) in auto):
                continue
            if (transfers.get((PM, maker, contract, token)) != amount or burns.get((PM, token)) != amount or amount <= 0):
                return None
            found.append({'token_id': str(token), 'quantity': str(Decimal(amount) / 1_000_000), 'cash_native': payout})
        views = proof.get('ctf_views', {})
        for redeemer, collateral, cid, payout in ctf:
            values = [result(views[data]) for data in ctf_calls(cid)]
            if any(re.fullmatch('0x[0-9a-fA-F]{64}', str(v)) is None for v in values):
                return None
            den, yes, no = (int(v, 16) for v in values[:3])
            if not den or yes + no != den:
                return None
            parts = []
            for collection, numerator in zip(values[3:], (yes, no)):
                token = int.from_bytes(keccak(bytes.fromhex(collateral[2:] + collection[2:])), 'big')
                if redeemer == maker:
                    amount = transfers.get((CTF, maker, ZERO, token), 0)
                else:
                    amount = transfers.get((CTF, maker, AUTO, token), 0)
                if amount and burns.get((CTF, token), 0) < amount:
                    return None
                if amount:
                    parts.append({'token_id': str(token), 'quantity': str(Decimal(amount) / 1_000_000),
                                  'cash_native': amount * numerator // den})
            if parts and sum(p['cash_native'] for p in parts) == payout:
                found.extend(parts)
        if (not found or outgoing or len({p['token_id'] for p in found}) != len(found) or
                sum(p['cash_native'] for p in found) != incoming):
            return None
        return {'transaction_hash': tx, 'positions': sorted(found, key=lambda p: p['token_id'])}
    except (ValueError, TypeError, KeyError, IndexError, OverflowError):
        return None
