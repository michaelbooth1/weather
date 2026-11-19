"""Exact historical external trades, admitted only by owner-operational close."""
from collections import Counter
from datetime import timedelta
import re

from eth_abi.exceptions import DecodingError

from weather.market.lfc_accounting import quantity, same_position
from weather.market.lfc_campaign_state import StateRefused
from weather.market.lfc_capital import ASSET, CapitalBook, SCALE, native
from weather.market.lfc_capital_native import hex_number, result, rpc_read, validate_asset, wallet_transfer_totals
from weather.market.lfc_f2_inventory import activity_start, expected_inventory
from weather.market.lfc_ledger import normalize_positions
from weather.market.lfc_recording_io import read_bytes, response_bytes, strict_json
from weather.market.lfc_redemption_native import BATCH, CTF, PM, SINGLE, address, unpack
from weather.market.mm_stage2_hold import digest, utc
from weather.operations.live_path_security import validate_regular_nonreparse_file


SCHEMA = 'lfc_owner_external_close_v1'
MAX_TRADES = 4
EXCHANGES = {'0xe111180000d2663c0091e4f400237545b87b996b', '0xe2222d279d744050d28e00520010520000310f59'}
ORDER_FILLED = '0xd543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee'
DECODE_ERRORS = (KeyError, TypeError, ValueError, ArithmeticError, AttributeError, DecodingError)


def hash32(value):
    if not isinstance(value, str) or not re.fullmatch(r'0x[0-9a-fA-F]{64}', value):
        raise ValueError('owner_external_identity')
    return value.lower()


def coverage(read):
    return min(utc(read['component_times'][name]['started_at_utc'])
               for name in ('trades', 'positions', 'balances'))


def attempt_bands(ledger, attempt):
    bands = [session for session in ledger.sessions.values()
             if session['start'].get('autostart_attempt_id') == attempt
             and session['start'].get('protocol') in {'lfc_autostart_v2', 'lfc_autostart_v3'}]
    if not bands or any(session['end'] is None for session in bands):
        raise StateRefused('owner_external_attempt_scope')
    return bands


def normalized_sources(book, read, attempt, cut):
    """Compare all new own executions, including those seen after the historical cut."""
    wallet = book.ledger.rows[0]['maker_address'].lower()
    ids = book.ledger.our_order_ids()
    bands = attempt_bands(book.ledger, attempt)
    markets = {s['start']['condition_id'] for s in bands}
    start = min(utc(s['start']['recorded_at_utc']) for s in bands)
    finish = max(utc(s['end']['recorded_at_utc']) for s in bands)
    anchor = utc(book.inventory_anchor['snapshot_at_utc'])
    sources, counts = {}, Counter()
    for row in read['trades']:
        tx = str(row.get('transaction_hash') or '').lower()
        counts[tx] += 1
        role = str(row.get('trader_side', '')).upper()
        if role == 'TAKER' and str(row.get('maker_address', '')).lower() == wallet:
            parts = [(row.get('taker_order_id'), row, 'size')]
        elif role == 'MAKER':
            parts = [(part.get('order_id'), part, 'matched_amount') for part in row.get('maker_orders') or ()
                     if str(part.get('maker_address', '')).lower() == wallet]
        else:
            parts = []
        if not parts or all(oid in ids for oid, _, _ in parts) or row.get('status') == 'FAILED':
            continue
        when = utc(row['matched_at'])
        if when < anchor:
            continue
        if when < start or when > finish or cut - when < timedelta(seconds=1):
            raise StateRefused('owner_external_trade_outside_cut')
        if len(parts) != 1 or row.get('status') != 'CONFIRMED':
            raise StateRefused('owner_external_trade_unconfirmed')
        (oid, part, size_key), = parts
        condition = hash32(row['market'])
        token = str(part.get('token_id', part.get('asset_id')))
        trade_id = row['id']
        order_ids = {row.get('taker_order_id'), *(m.get('order_id') for m in row.get('maker_orders') or ())}
        if condition in markets or token in book.ledger.tokens() or ids & order_ids or trade_id in ids:
            raise StateRefused('owner_external_campaign_overlap')
        if row.get('condition_id', condition) != condition:
            raise StateRefused('owner_external_identity')
        if not isinstance(trade_id, str) or not trade_id.strip() or len(trade_id) > 256:
            raise StateRefused('owner_external_identity')
        tx = hash32(tx)
        if tx in sources or any(source['trade_id'] == trade_id for source in sources.values()):
            raise StateRefused('owner_external_trade_set_changed')
        sources[tx] = {'trade_id': trade_id, 'order_id': hash32(oid), 'condition_id': condition,
                       'token_id': token, 'side': part['side'], 'price': str(quantity(part['price']).normalize()),
                       'quantity': str(quantity(part[size_key]).normalize()), 'matched_at': when.isoformat()}
    if len(sources) > MAX_TRADES or any(counts[tx] != 1 for tx in sources):
        raise StateRefused('owner_external_trade_set_changed')
    return sources


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


def receipt_facts(wallet, tx, source, packet):
    """Prove exact wallet collateral legs as well as the corresponding token legs."""
    receipt = result(packet)
    cash = wallet_transfer_totals(receipt, tx, wallet)
    side, token = source['side'], source['token_id']
    size, price = quantity(source['quantity']), quantity(source['price'])
    if (not re.fullmatch(r'[1-9][0-9]{0,77}', token) or side not in {'BUY', 'SELL'} or
            not 0 < price <= 1 or not size):
        raise StateRefused('owner_external_trade_terms')
    amount = native(size)
    position_transfer(receipt, tx, wallet, token, amount, side)
    gross = native(price * size, ceil=True) if side == 'BUY' else int(price * size * SCALE)
    fee = exchange_fee(receipt, tx, wallet, source['order_id'], token, side, gross, amount)
    allowed_cash = ({(0, gross + fee)} if side == 'BUY' else {(gross - fee, 0), (gross, fee)})
    if (cash['IN'], cash['OUT']) not in allowed_cash:
        raise StateRefused('owner_external_cash_legs_changed')
    return {'transaction_hash': tx, 'block_hash': hash32(receipt['blockHash']),
            'block_number': hex_number(receipt['blockNumber']), 'shares_native': amount, 'gross_native': gross,
            'fee_native': fee, 'cash_in_native': cash['IN'], 'cash_out_native': cash['OUT']}


def activity_digest(ledger, read):
    from weather.market.lfc_capital_reads import validate_packet
    packet = read['capital_activity']
    start = activity_start(ledger, read['started_at_utc'])
    end = packet['scope']['end']
    if type(end) is not int or not int(utc(read['ended_at_utc']).timestamp()) - 120 <= end <= int(
            utc(read['ended_at_utc']).timestamp()):
        raise StateRefused('owner_external_activity_cut')
    rows = validate_packet(packet, maker=ledger.rows[0]['maker_address'], start=start, end=end)
    validate_asset(packet['native_asset_proof'])
    return digest(sorted(rows, key=digest))


def build_facts(ledger, incident, incident_sha, attempt, read, receipts):
    """Pure formatter for copied evidence. It never obtains an account or chain read."""
    book = CapitalBook(ledger)
    if book.inventory_anchor is None:
        raise StateRefused('owner_external_anchor_missing')
    cut = coverage(read)
    sources = normalized_sources(book, read, attempt, cut)
    if not sources or set(sources) != set(receipts):
        raise StateRefused('owner_external_trade_set_changed')
    wallet = ledger.rows[0]['maker_address'].lower()
    return {'schema': SCHEMA, 'incident_id': incident, 'incident_sha256': incident_sha, 'attempt_id': attempt,
            'anchor_sha256': digest(book.inventory_anchor), 'coverage_utc': cut.isoformat(),
            'activity_sha256': activity_digest(ledger, read),
            'trades': [{'source': sources[tx], 'receipt': receipt_facts(wallet, tx, sources[tx], receipts[tx])}
                       for tx in sorted(sources)]}


def load_facts(path, sha):
    try:
        raw = read_bytes(validate_regular_nonreparse_file(path.absolute()), 64_000)
        facts = strict_json(raw)
        if (facts['schema'] != SCHEMA or digest(facts) != sha or
                not 1 <= len(facts['trades']) <= MAX_TRADES):
            raise ValueError('facts binding')
    except (OSError, RuntimeError, *DECODE_ERRORS):
        raise StateRefused('owner_external_facts_binding') from None
    return facts


def reconcile(book, packet, *, already_booked=False, sequence=None):
    """Verify the packet against the original book and apply only on an owner-close row."""
    facts, receipts = packet['facts'], packet['receipts']
    if (facts['schema'] != SCHEMA or packet['facts_sha256'] != digest(facts) or
            facts['anchor_sha256'] != digest(book.inventory_anchor) or
            not 1 <= len(facts['trades']) <= MAX_TRADES or
            set(receipts) != {item['receipt']['transaction_hash'] for item in facts['trades']} or
            len(facts['trades']) != len(receipts)):
        raise StateRefused('owner_external_facts_binding')
    if sum(len(response_bytes(receipt)) for receipt in receipts.values()) > 512_000:
        raise StateRefused('owner_external_receipt_budget')
    wallet = book.ledger.rows[0]['maker_address'].lower()
    bands = attempt_bands(book.ledger, facts['attempt_id'])
    campaign_conditions = {band['start']['condition_id'] for band in bands}
    owned = book.ledger.tokens()
    order_ids = book.ledger.our_order_ids()
    projected = expected_inventory(book.ledger, book.inventory_anchor, book, cut=sequence)
    deltas, cash, personal = Counter(), 0, []
    for item in facts['trades']:
        source, expected = item['source'], item['receipt']
        tx = expected['transaction_hash']
        if (source['condition_id'] in campaign_conditions or source['token_id'] in owned or
                source['trade_id'] in order_ids or source['order_id'] in order_ids):
            raise StateRefused('owner_external_campaign_overlap')
        if tx in book.activity_transactions.values():
            raise StateRefused('owner_external_trade_already_booked')
        observed = receipt_facts(wallet, tx, source, receipts[tx])
        if observed != expected:
            raise StateRefused('owner_external_receipt_changed')
        signed = observed['cash_in_native'] - observed['cash_out_native']
        cash += signed
        delta = quantity(source['quantity']) * (1 if source['side'] == 'BUY' else -1)
        deltas[source['token_id']] += delta
        key = source['trade_id'] + '/' + source['order_id']
        if (key in book.personal_trades) != already_booked:
            raise StateRefused('owner_external_trade_already_booked')
        personal.append((key, source, observed, delta))
    if not already_booked:
        for token, delta in deltas.items():
            expected = quantity(projected.get(token, 0)) + delta
            if expected < 0:
                raise StateRefused('owner_external_inventory_changed')
            projected[token] = str(expected)
    positions = packet['positions']
    for token in set(projected) | set(positions):
        before, after = projected.get(token, 0), positions.get(token, 0)
        equal = same_position(before, after) if token in owned else quantity(before) == quantity(after)
        if not equal:
            raise StateRefused('owner_external_inventory_changed')
    if packet['cash_native'] != book.expected_cash() + (0 if already_booked else cash):
        raise StateRefused('owner_external_cash_changed')
    if sequence is None:
        return
    for key, source, observed, delta in personal:
        book.personal_trades[key] = {'id': key, 'order_id': source['order_id'],
            'timestamp': utc(source['matched_at']).timestamp(), 'side': source['side'],
            'cash_native': observed['gross_native'], 'fee_native': observed['fee_native'],
            'source_sha256': digest(source)}
        book.owner_inventory_adjustments.append({'activity_id': 'personal-' + key, 'sequence': sequence,
            'token_id': source['token_id'], 'delta': str(delta), 'read_sha256': packet['read_sha256']})
        book.cash_in += observed['cash_in_native']
        book.cash_out += observed['cash_out_native']
    book.owner_external_close_cash += cash


def live_proof(runtime, ledger, incident, occurrence_sha, attempt, read, facts):
    """This is called only by the interactive owner-close path."""
    if runtime.task_enabled() or ledger.open_sessions() or ledger.unresolved_legs() or read.get('open_orders') != []:
        raise StateRefused('owner_external_requires_disabled_terminal_account')
    if (facts.get('incident_id'), facts.get('incident_sha256'), facts.get('attempt_id')) != (
            incident, occurrence_sha, attempt):
        raise StateRefused('owner_external_facts_binding')
    old = next(iter(ledger.event_rows('autostart_owner_close', field='incident_id', value=incident)), None)
    if old is not None and old['proof'].get('owner_external_close', {}).get('facts_sha256') != digest(facts):
        raise StateRefused('owner_external_facts_binding')
    if old is None and (not any(c['attempt_id'] == attempt for c in ledger.autostart_claims) or any(
            ledger.event_rows(event, field='attempt_id', value=attempt)
            for event in ('autostart_close', 'autostart_no_intent_close'))):
        raise StateRefused('owner_external_attempt_scope')
    traded = runtime.account_read_preflight(ledger, read)
    if ledger.trade_mismatches(traded):
        raise StateRefused('owner_external_campaign_trade_mismatch')
    book = CapitalBook(ledger)
    if book.inventory_anchor is None or facts.get('anchor_sha256') != digest(book.inventory_anchor):
        raise StateRefused('owner_external_anchor_changed')
    try:
        cut = utc(facts['coverage_utc'])
        if coverage(read) < cut or activity_digest(ledger, read) != facts['activity_sha256']:
            raise StateRefused('owner_external_activity_cut')
        sources = normalized_sources(book, read, attempt, cut)
        expected = {item['receipt']['transaction_hash']: item['source'] for item in facts['trades']}
        if sources != expected:
            raise StateRefused('owner_external_trade_set_changed')
        cash = native(read['balances']['available_collateral'])
        collateral = [native(value) for asset, value in read['balances']['assets'].items() if asset.lower() == ASSET]
        if (collateral != [cash] or
                str(read['balances']['collateral_evidence']['balance']) != str(cash)):
            raise StateRefused('owner_external_collateral_identity')
        receipts = {tx: rpc_read('eth_getTransactionReceipt', [tx]) for tx in sorted(sources)}
        packet = {'facts': facts, 'facts_sha256': digest(facts), 'read_sha256': digest(read),
                  'positions': normalize_positions(read['positions']), 'cash_native': cash, 'receipts': receipts}
        reconcile(book, packet, already_booked=old is not None)
    except OSError:
        raise StateRefused('owner_external_receipt_unavailable') from None
    except DECODE_ERRORS as exc:
        raise StateRefused('owner_external_proof_invalid') from exc
    runtime.account_read_preflight(ledger, read)
    book.gate(reserve='0', owner_fault_review=True)
    return {'money_accounting_complete': True, 'cleanup_proven': True, 'unknown_submit': False,
            'money_contradiction': False, 'ledger_head_sha256': ledger.previous, 'read_sha256': digest(read),
            'owner_external_close': packet, 'open_orders': 0}
