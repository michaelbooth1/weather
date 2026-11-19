"""Native, receipt-bound accounting of personal trades during an F2 attempt."""
from collections import Counter
import re

from eth_abi.exceptions import DecodingError

from weather.market.lfc_accounting import quantity, same_position
from weather.market.lfc_capital import CapitalBook, CapitalRefused, SCALE, native
from weather.market.lfc_capital_native import (hex_number, result, rpc_read, validate_asset,
                                                wallet_transfer_totals)
from weather.market.lfc_f2_inventory import expected_inventory
from weather.market.lfc_ledger import normalize_positions
from weather.market.lfc_recording_io import PublicReadFailure, response_bytes
from weather.market.lfc_redemption_native import BATCH, CTF, PM, SINGLE, address, unpack
from weather.market.mm_stage2_hold import digest, utc


NOTICE = 'account_external_trade_notice'
STOP = 'account_external_trade_unproved'
MAX_RECEIPTS = 4
MAX_PROOF_BYTES = 512_000
# Polygon CTF Exchange V2 and NegRisk CTF Exchange V2. Pin the emitters and
# ITrading.OrderFilled topic so a different on-chain transfer cannot set a fee.
EXCHANGES = {'0xe111180000d2663c0091e4f400237545b87b996b', '0xe2222d279d744050d28e00520010520000310f59'}
ORDER_FILLED = '0xd543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee'


def hash32(value):
    if not isinstance(value, str) or re.fullmatch(r'0x[0-9a-fA-F]{64}', value) is None:
        raise ValueError('external_trade_identity')
    return value.lower()


def own_parts(row, wallet):
    """The account-wide SDK and socket carry the same wallet and allocation roles."""
    role = str(row.get('trader_side', '')).upper()
    if role == 'TAKER' and str(row.get('maker_address', '')).lower() == wallet:
        return [(row.get('taker_order_id'), row, 'size')]
    if role == 'MAKER':
        return [(part.get('order_id'), part, 'matched_amount')
                for part in row.get('maker_orders', ()) or ()
                if isinstance(part, dict) and str(part.get('maker_address', '')).lower() == wallet]
    return []


def notice_for(row, wallet):
    """Only identify a scoped hint. The socket cannot grant accounting authority."""
    if (str(row.get('event_type', '')).lower() != 'trade' or
            str(row.get('status', '')).upper() not in {'MATCHED', 'MINED', 'CONFIRMED', 'RETRYING'} or
            not own_parts(row, wallet.lower())):
        return None
    try:
        tx = row.get('transaction_hash')
        notice = {'trade_id': row['id'], 'condition_id': hash32(row['market']),
                  'transaction_hash': hash32(tx) if tx else None}
        validate_notice(notice, pending=True)
    except (KeyError, ValueError):
        return None
    return {'event_type': NOTICE, **notice, 'raw_event_sha256': digest(row)}


def validate_notice(row, *, pending=False):
    if not isinstance(row.get('trade_id'), str) or not row['trade_id'].strip() or len(row['trade_id']) > 256:
        raise ValueError('external_trade_identity')
    hash32(row.get('condition_id'))
    if not pending or row.get('transaction_hash') is not None:
        hash32(row.get('transaction_hash'))


def pending_scope(ledger):
    """Only a currently open or not-yet-closed F2 attempt can grant new proof."""
    closed = {r['attempt_id'] for event in ('autostart_close', 'autostart_no_intent_close')
              for r in ledger.event_rows(event)}
    attempts = {r['attempt_id'] for r in ledger.autostart_claims} - closed
    bands = [s for s in ledger.sessions.values() if s['start'].get('autostart_attempt_id') in attempts
             and s['start'].get('protocol') in {'lfc_autostart_v2', 'lfc_autostart_v3'}]
    band_attempts = {s['start']['autostart_attempt_id'] for s in bands}
    if len(band_attempts) != 1:
        return None
    (attempt,) = band_attempts
    start = min(utc(s['start']['recorded_at_utc']) for s in bands)
    end = (max(utc(s['end']['recorded_at_utc']) for s in bands) if all(s['end'] for s in bands) else None)
    return attempt, start, end


def snapshot_time(read):
    times = read['component_times']
    return min(utc(times[name]['started_at_utc']) for name in ('trades', 'positions', 'balances'))


def candidates(book, read, scope):
    """Select confirmed, unsplit owner executions in the pending attempt interval."""
    ledger = book.ledger
    wallet, ids = ledger.rows[0]['maker_address'].lower(), ledger.our_order_ids()
    attempt, start, finish = scope
    through = snapshot_time(read)
    positions = ledger.tokens()
    markets = {s['start'].get('condition_id') for s in ledger.sessions.values()}
    after = max(start, utc(book.inventory_anchor['snapshot_at_utc']))
    grouped = Counter()
    bound_here = {tx for tx, bound_attempt in book.external_trade_attempts.items() if attempt == bound_attempt}
    found, seen_bound, later = {}, set(), False
    for row in read['trades']:
        tx = str(row.get('transaction_hash', '')).lower()
        if tx:
            grouped[tx] += 1
        parts = own_parts(row, wallet)
        if not parts or all(oid in ids for oid, _, _ in parts) or row.get('status') == 'FAILED':
            continue
        # Known personal activity belongs to its original reference, even when
        # the SDK returns the same trade in the exhaustive account history.
        when = utc(row['matched_at'])
        if when < after:
            continue
        trade_id = row['id']
        if all(f'{trade_id}/{oid}' in book.personal_trades for oid, _, _ in parts) and tx not in book.external_trade_transactions:
            continue
        if finish is not None and when > finish:
            later = True
            continue
        if row.get('status') != 'CONFIRMED' or through.timestamp() < when.timestamp() + 1:
            continue
        if len(parts) != 1:
            raise ValueError('external_trade_allocation')
        (oid, part, size_key), = parts
        order_ids = {row.get('taker_order_id')}
        order_ids.update(m.get('order_id') for m in (row.get('maker_orders') or ()) if isinstance(m, dict))
        condition = hash32(row.get('market'))
        token = part.get('token_id', part.get('asset_id'))
        if (condition in markets or str(token) in positions or ids & order_ids or trade_id in ids or
                row.get('condition_id', condition) != condition):
            raise ValueError('external_trade_campaign_overlap')
        source = {'trade_id': trade_id, 'order_id': hash32(oid), 'condition_id': condition,
                  'token_id': str(token), 'side': part['side'], 'quantity': str(quantity(part[size_key])),
                  'price': str(quantity(part['price'])), 'wallet': wallet, 'status': 'CONFIRMED',
                  'transaction_hash': hash32(tx), 'matched_at': when.isoformat()}
        validate_notice(source)
        if tx in book.external_trade_transactions:
            bound = book.personal_trades.get(f'{trade_id}/{oid}', {})
            if bound.get('source_sha256') != digest(source):
                raise ValueError('external_trade_binding')
            seen_bound.add(tx)
            continue
        if tx in found:
            raise ValueError('external_trade_batched_receipt')
        found[tx] = source
    if bound_here - seen_bound or (found or bound_here) and later:
        raise ValueError('external_trade_outside_attempt')
    if len(found) > MAX_RECEIPTS or any(grouped[tx] != 1 for tx in found):
        raise ValueError('external_trade_batched_receipt')
    return found


def collect_receipts(ledger, read, *, rpc=rpc_read):
    """A bounded public read for independently confirmed execution candidates."""
    scope = pending_scope(ledger)
    if scope is None:
        return {}
    book = CapitalBook(ledger)
    if book.inventory_anchor is None:
        return {}
    try:
        sources = candidates(book, read, scope)
    except (KeyError, TypeError, ValueError, ArithmeticError, AttributeError):
        return {}  # The same finite selector refuses in proof, before writing.
    receipts, size = {}, 0
    for tx in sources:
        try:
            packet = rpc('eth_getTransactionReceipt', [tx])
            size += len(response_bytes(packet))
            receipts[tx] = packet if size <= MAX_PROOF_BYTES else None
        except (OSError, PublicReadFailure):
            receipts[tx] = None
    return receipts


def log_index(receipt, log, tx):
    if (log.get('removed', False) is not False or log.get('transactionHash', '').lower() != tx or
            log.get('blockHash', receipt['blockHash']).lower() != receipt['blockHash'].lower() or
            hex_number(log.get('blockNumber', receipt['blockNumber'])) != hex_number(receipt['blockNumber'])):
        raise ValueError('external_trade_receipt_log')
    return hex_number(log['logIndex'])


def exchange_fee(receipt, tx, wallet, oid, token, side, gross, amount):
    """Require a single V2 fill binding its owner order, gross, fees and size."""
    matches = []
    for log in receipt['logs']:
        topics = log.get('topics') or []
        if log.get('address', '').lower() not in EXCHANGES or not topics or topics[0] != ORDER_FILLED:
            continue
        log_index(receipt, log, tx)
        if len(topics) != 4:
            raise ValueError('external_trade_exchange_log')
        if address(topics[2]) == wallet:
            matches.append(log)
    if len(matches) != 1 or matches[0]['topics'][1].lower() != oid:
        raise ValueError('external_trade_exchange_order')
    direction, asset, making, taking, fee, _, _ = unpack(matches[0], 4,
        ['uint8', 'uint256', 'uint256', 'uint256', 'uint256', 'bytes32', 'bytes32'])
    expected = (0, int(token), gross, amount) if side == 'BUY' else (1, int(token), amount, gross)
    if (direction, asset, making, taking) != expected or fee > gross:
        raise ValueError('external_trade_exchange_quantity')
    return fee


def position_transfer(receipt, tx, wallet, token, amount, side):
    """Require the wallet's entire CTF/PM token movement in this receipt."""
    incoming, outgoing, indices = 0, 0, set()
    for log in receipt['logs']:
        topics = log.get('topics') or []
        if log.get('address', '').lower() not in {CTF, PM} or not topics or topics[0] not in {SINGLE, BATCH}:
            continue
        index = log_index(receipt, log, tx)
        if index in indices:
            raise ValueError('external_trade_receipt_log')
        indices.add(index)
        if topics[0] == SINGLE:
            asset, shares = unpack(log, 4, ['uint256', 'uint256'])
            pairs = [(asset, shares)]
        else:
            ids, sizes = unpack(log, 4, ['uint256[]', 'uint256[]'])
            pairs = list(zip(ids, sizes, strict=True))
        sender, receiver = address(topics[2]), address(topics[3])
        if (sender == wallet) == (receiver == wallet):
            continue
        if any(str(asset) != token for asset, shares in pairs if shares):
            raise ValueError('external_trade_receipt_asset')
        moved = sum(shares for _, shares in pairs)
        if receiver == wallet:
            incoming += moved
        else:
            outgoing += moved
    if (incoming, outgoing) != ((amount, 0) if side == 'BUY' else (0, amount)):
        raise ValueError('external_trade_receipt_position')


def trade_facts(book, source, packet, scope, through):
    ledger = book.ledger
    _, start, finish = scope
    when = utc(source['matched_at'])
    wallet, tx = source['wallet'], hash32(source['transaction_hash'])
    pos = quantity(source['quantity'])
    price = quantity(source['price'])
    oid, token, side = hash32(source['order_id']), source['token_id'], source['side']
    validate_notice(source)
    key = source['trade_id'] + '/' + oid
    if (wallet != ledger.rows[0]['maker_address'].lower() or source['status'] != 'CONFIRMED' or
            when < max(start, utc(book.inventory_anchor['snapshot_at_utc'])) or
            (finish is not None and when > finish) or through.timestamp() < when.timestamp() + 1 or
            source['condition_id'] in {s['start'].get('condition_id') for s in ledger.sessions.values()} or
            token in ledger.tokens() or oid in ledger.our_order_ids() or source['trade_id'] in ledger.our_order_ids() or
            key in book.personal_trades or tx in book.external_trade_transactions or
            not re.fullmatch(r'[1-9][0-9]{0,77}', token) or side not in {'BUY', 'SELL'} or
            not 0 < price <= 1 or not pos):
        raise ValueError('external_trade_scope')
    receipt = result(packet)
    cash = wallet_transfer_totals(receipt, tx, wallet)
    amount = native(pos)
    position_transfer(receipt, tx, wallet, token, amount, side)
    gross = native(price * pos, ceil=True) if side == 'BUY' else int(price * pos * SCALE)
    fee = exchange_fee(receipt, tx, wallet, oid, token, side, gross, amount)
    signed = (-gross if side == 'BUY' else gross) - fee
    if cash['IN'] - cash['OUT'] != signed:
        raise ValueError('external_trade_receipt_cash')
    item = {'id': key, 'order_id': oid, 'timestamp': when.timestamp(), 'side': side,
            'cash_native': gross, 'fee_native': fee, 'source_sha256': digest(source)}
    return item, signed, pos if side == 'BUY' else -pos


def apply_external_trades(book, row):
    """Recompute position and native cash equality before marking the ledger event valid."""
    packet = row['external_trades']
    scope = pending_scope(book.ledger)
    groups = packet['groups']
    through = utc(packet['through_utc'])
    if (scope is None or packet['attempt_id'] != scope[0] or
            packet['inventory_anchor_sha256'] != digest(book.inventory_anchor) or
            row['read_sha256'] != packet['read_sha256'] or
            row['proof_sha256'] != digest(packet) or
            re.fullmatch(r'[0-9a-f]{64}', packet['read_sha256']) is None or
            through > utc(row['recorded_at_utc']) or not 1 <= len(groups) <= MAX_RECEIPTS):
        raise ValueError('external_trade_binding')
    validate_asset(packet['native_asset_proof'])
    projected = expected_inventory(book.ledger, book.inventory_anchor, book, cut=row['sequence'])
    deltas, net, pending = Counter(), 0, []
    for tx, group in groups.items():
        source = group['source']
        if tx != source['transaction_hash']:
            raise ValueError('external_trade_binding')
        item, signed, delta = trade_facts(book, source, group['receipt'], scope, through)
        deltas[source['token_id']] += delta
        net += signed
        pending.append((tx, source, item, signed, delta))
    for token, delta in deltas.items():
        following = quantity(projected.get(token, 0)) + delta
        if following < 0:
            raise ValueError('external_trade_inventory')
        projected[token] = str(following)
    if any(not same_position(projected.get(token, 0), packet['positions'].get(token, 0))
           for token in (set(projected) | packet['positions'].keys()) - deltas.keys()) or any(
               quantity(projected.get(token, 0)) != quantity(packet['positions'].get(token, 0)) for token in deltas):
        raise ValueError('external_trade_inventory')
    if packet['cash_native'] != book.expected_cash() + net:
        raise CapitalRefused('capital_cash_unreconciled')

    for tx, source, item, signed, delta in pending:
        key, stamp, sequence = item['id'], item['timestamp'], row['sequence']
        book.personal_trades[key] = item
        book.external_trade_transactions[tx] = source['trade_id']
        book.external_trade_attempts[tx] = scope[0]
        book.owner_inventory_adjustments.append({'activity_id': 'personal-' + key, 'sequence': sequence,
            'token_id': source['token_id'], 'delta': str(delta), 'read_sha256': row['read_sha256']})
        debit = item['fee_native'] + (item['cash_native'] if item['side'] == 'BUY' else 0)
        if debit:
            book.pool_movements.append({'kind': 'withdraw', 'amount': debit, 'timestamp': stamp,
                                        'sequence': sequence, 'charge_excess': False})
            book.pools_dirty = True
        if item['side'] == 'SELL':
            book.credit('external', item['cash_native'], {'id': 'personal-' + key, 'timestamp': stamp},
                        sequence=sequence)
        if signed > 0:
            book.cash_in += signed
        else:
            book.cash_out -= signed


def reconcile(book, read):
    """Append one proof only after a complete independent account read agrees."""
    from weather.market.lfc_campaign import TransientPrecheck

    scope = pending_scope(book.ledger)
    if scope is None or book.inventory_anchor is None:
        return False
    try:
        sources = candidates(book, read, scope)
        if not sources:
            if (scope[0] in book.external_trade_attempts.values() and
                    native(read['balances']['available_collateral']) != book.expected_cash()):
                raise CapitalRefused('capital_cash_unreconciled')
            return False
        receipts = read.get('external_trade_receipts', {})
        if any(receipts.get(tx) is None or result(receipts[tx]) is None for tx in sources):
            raise TransientPrecheck('external_trade_proof_pending')
        packet = {'attempt_id': scope[0], 'inventory_anchor_sha256': digest(book.inventory_anchor),
                  'read_sha256': digest(read), 'through_utc': snapshot_time(read).isoformat(),
                  'cash_native': native(read['balances']['available_collateral']),
                  'positions': normalize_positions(read['positions']),
                  'native_asset_proof': read['capital_activity']['native_asset_proof'],
                  'groups': {tx: {'source': source, 'receipt': receipts[tx]} for tx, source in sources.items()}}
        if sum(len(response_bytes(receipts[tx])) for tx in sources) > MAX_PROOF_BYTES:
            raise ValueError('external_trade_receipt_budget')
        fields = {'external_trades': packet, 'proof_sha256': digest(packet), 'read_sha256': packet['read_sha256']}
        # Test against the detached book first. The ledger replay repeats the
        # same proof at the same cut and rejects an altered or duplicate row.
        apply_external_trades(book, {**fields, 'sequence': len(book.ledger.rows),
                                     'recorded_at_utc': book.ledger.clock().isoformat()})
    except CapitalRefused:
        raise
    except (KeyError, TypeError, ValueError, ArithmeticError, AttributeError, DecodingError):
        raise CapitalRefused('capital_inventory_unreconciled') from None
    book.ledger.record('capital_external_trades', **fields)
    return True


def prove_live(runtime, ledger, attempt_id, notice):
    """Return the independently bound transaction if this quote loop can resume."""
    from weather.market.lfc_campaign_state import StateRefused
    from weather.market.lfc_capital_reads import synchronize

    began = runtime.clock.monotonic()
    read = runtime.read_account()
    # Use ordinary cleanup if the read took the quote checkpoint budget.
    if runtime.clock.monotonic() - began > 12:
        return None
    try:
        runtime.account_read_preflight(ledger, read)
    except StateRefused as exc:
        if str(exc) != 'account_read_binding':
            raise
        return None
    book = CapitalBook(ledger)
    scope = pending_scope(ledger)
    if scope is None or scope[0] != attempt_id or book.inventory_anchor is None:
        return None
    try:
        sources = candidates(book, read, scope)
    except (KeyError, TypeError, ValueError, ArithmeticError, AttributeError):
        return None
    matches = [tx for tx, source in sources.items()
               if source['trade_id'] == notice['trade_id'] and source['condition_id'] == notice['condition_id']
               and notice['transaction_hash'] in (None, tx)]
    if len(matches) != 1:
        return None
    (tx,) = matches
    proof = synchronize(ledger, runtime.original_baseline(ledger), read, live_proof={'attempt_id': attempt_id})
    if (proof.get('cash_bridge_complete') is True and
            CapitalBook(ledger).external_trade_transactions.get(tx) == notice['trade_id'] and
            runtime.clock.monotonic() - began <= 12):
        return tx
    return None
