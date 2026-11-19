"""Historical native balance witnesses for tiny positions omitted by the public index."""
from decimal import Decimal
import re

from weather.market.lfc_accounting import same_position
from weather.market.lfc_campaign_state import StateRefused
from weather.market.lfc_capital import SCALE
from weather.market.lfc_capital_native import hex_number, result, rpc_read
from weather.market.lfc_redemption_native import CTF, call_data
from weather.market.lfc_recording_io import response_bytes


BALANCE_SELECTOR = call_data('balanceOf(address,uint256)', ['address', 'uint256'], ['0x' + '0'*40, 1])[:10]
INDEX_OMISSION_LIMIT = Decimal('0.01')
BLOCK_TAG = re.compile(r'0x(?:0|[1-9a-f][0-9a-f]*)')
HASH = re.compile(r'0x[0-9a-f]{64}')


def permitted_inventory_read(method, params):
    if len(params) != 2:
        return False
    first, second = params
    if method == 'eth_getBlockByNumber':
        return second is False and isinstance(first, str) and (first == 'latest' or BLOCK_TAG.fullmatch(first))
    if method != 'eth_call' or not isinstance(first, dict) or set(first) != {'to', 'data'} or first['to'] != CTF:
        return False
    data = first['data']
    return (isinstance(data, str) and re.fullmatch(BALANCE_SELECTOR + r'0{24}[0-9a-f]{104}', data) is not None
            and isinstance(second, str) and BLOCK_TAG.fullmatch(second) is not None)


def header(raw):
    row = result(raw)
    number, timestamp = hex_number(row['number']), hex_number(row['timestamp'])
    if any(not HASH.fullmatch(row[k]) for k in ('hash', 'parentHash')):
        raise StateRefused('owner_external_native_block_binding')
    return number, timestamp, row['hash'], row['parentHash']


def block_at_cut(block, lower, upper, cut):
    """Retain two consecutive headers bracketing the requested observation time."""
    if not lower[1][1] <= cut.timestamp() < upper[1][1]:
        raise StateRefused('owner_external_native_block_cut')
    for _ in range(40):
        lo, hi = lower[1][0], upper[1][0]
        if hi - lo == 1:
            return [lower[0], upper[0]]
        # Binary steps cap the cost even when timestamp density changes.
        middle = block(hex((lo + hi)//2))
        if middle[1][1] <= cut.timestamp():
            lower = middle
        else:
            upper = middle
    raise StateRefused('owner_external_native_block_budget')


def collect_checkpoints(wallet, anchor, cut, tokens, first_trade_block):
    cache = {}

    def block(tag):
        if tag not in cache:
            raw = rpc_read('eth_getBlockByNumber', [tag, False], owner_inventory=True)
            info = header(raw)
            if tag != 'latest' and info[0] != int(tag, 16):
                raise StateRefused('owner_external_native_block_binding')
            cache[tag] = raw, info
        return cache[tag]

    upper = block('latest')
    lower = block(hex(max(0, first_trade_block-32_000)))
    if lower[1][1] > anchor.timestamp():
        lower = block('0x0')
    brackets = [block_at_cut(block, lower, upper, when) for when in (anchor, cut)]
    checkpoints = [header(pair[0]) for pair in brackets]
    balances = {}
    for token in sorted(tokens):
        data = call_data('balanceOf(address,uint256)', ['address', 'uint256'], [wallet, int(token)])
        balances[token] = [rpc_read('eth_call', [{'to': CTF, 'data': data}, hex(info[0])], owner_inventory=True)
                           for info in checkpoints]
    for info in checkpoints:
        again = rpc_read('eth_getBlockByNumber', [hex(info[0]), False], owner_inventory=True)
        if header(again) != info:
            raise StateRefused('owner_external_native_block_changed_retry')
    return {'brackets': brackets, 'balances': balances}


def native_corrections(witness, anchor, cut, omitted, trade_blocks):
    brackets, balances = witness['brackets'], witness['balances']
    if len(brackets) != 2 or set(balances) != set(omitted):
        raise StateRefused('owner_external_native_inventory_binding')
    raw = [item for pair in brackets for item in pair]
    raw.extend(item for pair in balances.values() for item in pair)
    if sum(len(response_bytes(item)) for item in raw) > 2_000_000:
        raise StateRefused('owner_external_native_inventory_budget')
    numbers = []
    for pair, when in zip(brackets, (anchor, cut), strict=True):
        before, after = map(header, pair)
        if (after[0] != before[0]+1 or after[3] != before[2] or
                not before[1] <= when.timestamp() < after[1]):
            raise StateRefused('owner_external_native_block_binding')
        numbers.append(before[0])
    if any(not numbers[0] < n <= numbers[1] for n in trade_blocks):
        raise StateRefused('owner_external_native_block_cut')
    corrections = {}
    for token, (baseline, delta) in omitted.items():
        raw_before, raw_after = (result(value) for value in balances[token])
        if any(not HASH.fullmatch(value) for value in (raw_before, raw_after)):
            raise StateRefused('owner_external_native_inventory_binding')
        before, after = (Decimal(int(value, 16))/SCALE for value in (raw_before, raw_after))
        if (not same_position(baseline, before) or after - before != delta or
                not 0 <= after < INDEX_OMISSION_LIMIT):
            raise StateRefused('owner_external_inventory_changed')
        corrections[token] = before - baseline
    return corrections
