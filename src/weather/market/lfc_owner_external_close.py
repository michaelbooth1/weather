"""Exact historical external trades, admitted only by owner-operational close."""
from collections import Counter
from datetime import timedelta
from decimal import Decimal
import re

from eth_abi.exceptions import DecodingError

from weather.market.lfc_accounting import POSITION_DUST, quantity, same_position
from weather.market.lfc_campaign_state import StateRefused
from weather.market.lfc_capital import ASSET, CapitalBook, SCALE, native
from weather.market.lfc_capital_native import hex_number, resolve, result, rpc_read, validate_asset, wallet_transfer_totals
from weather.market.lfc_f2_inventory import activity_start, expected_inventory
from weather.market.lfc_ledger import normalize_positions
from weather.market.lfc_recording_io import read_bytes, response_bytes, strict_json
from weather.market.lfc_redemption_native import BATCH, CTF, PM, SINGLE, address, unpack
from weather.market.mm_stage2_hold import digest, utc
from weather.operations.live_path_security import validate_regular_nonreparse_file
from weather.schema_registry import schema_version


SCHEMA = schema_version('lfc_owner_external_close_facts')
PROOF_SCHEMA = schema_version('lfc_owner_external_close_proof')
GAP_SCHEMA = schema_version('lfc_owner_external_close_proof_v4')
LEGACY_SCHEMA = schema_version('lfc_owner_external_close_proof_v2')
FRESH_SCHEMAS = {PROOF_SCHEMA, GAP_SCHEMA}
MAX_PINNED_TRADES = 4
MAX_TRADES = 32
PROTOCOL_MOVEMENTS = ('MERGE', 'DIRECTIONAL_MERGE', 'SPLIT', 'DIRECTIONAL_SPLIT', 'CONVERSION', 'MIGRATION',
                      'THRESHOLD_COMPOSE', 'THRESHOLD_DECOMPOSE')
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


def campaign_conditions(ledger, sequence=None):
    return {row.get('condition_id') for row in ledger.rows[:sequence]
            if row['event'] in ('session_start', 'leg_intent')}


def sdk_trade_source(row, part, order, size_key, when):
    condition, trade_id = hash32(row['market']), row['id']
    if row.get('condition_id', condition) != condition:
        raise StateRefused('owner_external_identity')
    if not isinstance(trade_id, str) or not trade_id.strip() or len(trade_id) > 256:
        raise StateRefused('owner_external_identity')
    return {'trade_id': trade_id, 'order_id': hash32(order), 'condition_id': condition,
            'token_id': str(part.get('token_id', part.get('asset_id'))), 'side': part['side'],
            'price': str(quantity(part['price']).normalize()),
            'quantity': str(quantity(part[size_key]).normalize()), 'matched_at': when.isoformat()}


def normalized_sources(book, read, attempt, cut, *, fresh=False):
    """Bind confirmed wallet executions to the requested historical or fresh cut."""
    wallet = book.ledger.rows[0]['maker_address'].lower()
    ids = book.ledger.our_order_ids()
    bands = attempt_bands(book.ledger, attempt)
    markets = campaign_conditions(book.ledger) if fresh else {s['start']['condition_id'] for s in bands}
    campaign_tokens = book.ledger.tokens()
    start = min(utc(s['start']['recorded_at_utc']) for s in bands)
    finish = max(utc(s['end']['recorded_at_utc']) for s in bands)
    anchor = utc(book.inventory_anchor['snapshot_at_utc'])
    sources, counts, trade_ids = {}, Counter(), set()
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
        if fresh and cut - when < timedelta(seconds=1):
            raise StateRefused('owner_external_trade_cut_retry')
        if not fresh and (when < start or when > finish or cut - when < timedelta(seconds=1)):
            raise StateRefused('owner_external_trade_outside_cut')
        if len(parts) != 1 or row.get('status') != 'CONFIRMED':
            raise StateRefused('owner_external_trade_unconfirmed')
        (oid, part, size_key), = parts
        source = sdk_trade_source(row, part, oid, size_key, when)
        trade_id = source['trade_id']
        order_ids = {row.get('taker_order_id'), *(m.get('order_id') for m in row.get('maker_orders') or ())}
        if source['condition_id'] in markets or source['token_id'] in campaign_tokens or ids & order_ids or trade_id in ids:
            raise StateRefused('owner_external_campaign_overlap')
        tx = hash32(tx)
        if tx in sources or trade_id in trade_ids:
            raise StateRefused('owner_external_trade_set_changed')
        trade_ids.add(trade_id)
        sources[tx] = source
        if fresh and len(sources) > MAX_TRADES:
            raise StateRefused('owner_external_trade_cap')
    if (not fresh and len(sources) > MAX_PINNED_TRADES) or any(counts[tx] != 1 for tx in sources):
        raise StateRefused('owner_external_trade_set_changed')
    return sources


def log_index(receipt, log, tx):
    if (log.get('removed', False) is not False or log.get('transactionHash', '').lower() != tx or
            log.get('blockHash', receipt['blockHash']).lower() != receipt['blockHash'].lower() or
            hex_number(log.get('blockNumber', receipt['blockNumber'])) != hex_number(receipt['blockNumber'])):
        raise ValueError('external_trade_receipt_log')
    return hex_number(log['logIndex'])


def exchange_amounts(receipt, tx, wallet, oid, token, side, gross, amount, *, improvement):
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
    shares, paid = (taking, making) if side == 'BUY' else (making, taking)
    price_matches = (paid <= gross if side == 'BUY' else paid >= gross) if improvement else paid == gross
    if (direction != (0 if side == 'BUY' else 1) or asset != int(token) or shares != amount or
            (improvement and not 0 < paid <= amount) or not price_matches or fee > paid):
        raise ValueError('external_trade_exchange_quantity')
    return paid, fee


def wallet_position_moves(receipt, tx, wallet):
    """Read the wallet's entire CTF/PM movements, without netting transfers."""
    incoming, outgoing, indices = Counter(), Counter(), set()
    contracts = {}
    for log in receipt['logs']:
        contract = log.get('address', '').lower()
        topics = log.get('topics') or []
        if contract not in {CTF, PM} or not topics or topics[0] not in {SINGLE, BATCH}:
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
        moved = incoming if receiver == wallet else outgoing
        for asset, shares in pairs:
            if shares:
                token = str(asset)
                moved[token] += shares
                contracts.setdefault(token, set()).add(contract)
    return dict(incoming), dict(outgoing), contracts


def position_transfer(receipt, tx, wallet, token, amount, side):
    incoming, outgoing, contracts = wallet_position_moves(receipt, tx, wallet)
    if (incoming, outgoing) != (({token: amount}, {}) if side == 'BUY' else ({}, {token: amount})):
        raise ValueError('external_trade_receipt_position')
    return contracts[token]


def receipt_facts(wallet, tx, source, packet, *, improvement=False, inventory_contracts=None):
    """Prove exact wallet collateral legs as well as the corresponding token legs."""
    receipt = result(packet)
    cash = wallet_transfer_totals(receipt, tx, wallet)
    side, token = source['side'], source['token_id']
    size, price = quantity(source['quantity']), quantity(source['price'])
    if (not re.fullmatch(r'[1-9][0-9]{0,77}', token) or side not in {'BUY', 'SELL'} or
            not 0 < price <= 1 or not size):
        raise StateRefused('owner_external_trade_terms')
    amount = native(size)
    contracts = position_transfer(receipt, tx, wallet, token, amount, side)
    gross = native(price * size, ceil=True) if side == 'BUY' else int(price * size * SCALE)
    gross, fee = exchange_amounts(receipt, tx, wallet, source['order_id'], token, side, gross, amount,
                                  improvement=improvement)
    allowed_cash = ({(0, gross + fee)} if side == 'BUY' else {(gross - fee, 0), (gross, fee)})
    if (cash['IN'], cash['OUT']) not in allowed_cash:
        raise StateRefused('owner_external_cash_legs_changed')
    if inventory_contracts is not None:
        inventory_contracts.setdefault(token, set()).update(contracts)
    return {'transaction_hash': tx, 'block_hash': hash32(receipt['blockHash']),
            'block_number': hex_number(receipt['blockNumber']), 'shares_native': amount, 'gross_native': gross,
            'fee_native': fee, 'cash_in_native': cash['IN'], 'cash_out_native': cash['OUT']}


def retained_activity(ledger, read):
    from weather.market.lfc_capital_reads import validate_packet
    packet = read['capital_activity']
    start = activity_start(ledger, read['started_at_utc'])
    end = packet['scope']['end']
    if type(end) is not int or not int(utc(read['ended_at_utc']).timestamp()) - 120 <= end <= int(
            utc(read['ended_at_utc']).timestamp()):
        raise StateRefused('owner_external_activity_cut')
    rows = validate_packet(packet, maker=ledger.rows[0]['maker_address'], start=start, end=end)
    validate_asset(packet['native_asset_proof'])
    return rows


def activity_digest(ledger, read):
    return digest(sorted(retained_activity(ledger, read), key=digest))


def refuse_movements(rows, anchor, booked):
    reasons = {'REDEEM': 'owner_external_redemption_unhandled',
               'MERGE': 'owner_external_merge_unhandled', 'DIRECTIONAL_MERGE': 'owner_external_merge_unhandled',
               'DEPOSIT': 'owner_external_transfer_unhandled', 'WITHDRAWAL': 'owner_external_transfer_unhandled',
               'TIP': 'owner_external_transfer_unhandled', 'TRANSFER': 'owner_external_transfer_unhandled'}
    for row in rows:
        if row['timestamp'] >= int(anchor.timestamp()) and str(row['transaction_hash']).lower() not in booked:
            raise StateRefused(reasons.get(row['type'], 'owner_external_activity_unhandled'))


def read_protocol_movements(wallet, anchor, cut):
    from weather.market.lfc_capital_reads import read_activity
    return read_activity(wallet, int(anchor.timestamp()), int(cut.timestamp()), types=PROTOCOL_MOVEMENTS)


def validate_protocol_movements(book, wallet, anchor, cut, packet):
    rows = protocol_rows(wallet, anchor, cut, packet)
    refuse_movements(rows, anchor, set(book.activity_transactions.values()))


def protocol_rows(wallet, anchor, cut, packet):
    from weather.market.lfc_capital_reads import validate_packet
    return validate_packet(packet, maker=wallet, start=int(anchor.timestamp()), end=int(cut.timestamp()),
                           types=PROTOCOL_MOVEMENTS)


def gap_sources(book, facts, rows, cut, movement, *, retained=()):
    from weather.market.lfc_owner_close_activity import sources

    finish = max(utc(band['end']['recorded_at_utc']) for band in attempt_bands(book.ledger, facts['attempt_id']))
    anchor = utc(book.inventory_anchor['snapshot_at_utc'])
    wallet = book.ledger.rows[0]['maker_address'].lower()
    return sources(book, [*rows, *protocol_rows(wallet, anchor, cut, movement)], finish, cut, retained=retained)


def gap_receipts(book, read, groups, *, reread=False):
    from weather.market.lfc_owner_close_activity import MAX_TRANSACTIONS, MERGES

    if len(groups) > MAX_TRANSACTIONS:
        raise StateRefused('owner_external_activity_cap')
    proofs = read['capital_activity']['native_receipts']
    result_groups = {}
    for tx, rows in sorted(groups.items()):
        if tx in proofs:
            bound = resolve(proofs[tx], book.ledger)
            if bound['rows'] != rows or bound['rows_sha256'] != digest(rows):
                raise StateRefused('owner_external_activity_binding')
        else:
            if any(row['type'] not in MERGES for row in rows):
                raise StateRefused('owner_external_activity_receipt_missing')
            bound = {'transaction_hash': tx, 'rows': rows, 'rows_sha256': digest(rows),
                     'receipt': rpc_read('eth_getTransactionReceipt', [tx]), 'failure_type': None}
        if reread and tx in proofs and result(rpc_read('eth_getTransactionReceipt', [tx])) != result(bound['receipt']):
            raise StateRefused('owner_external_activity_receipt_changed')
        result_groups[tx] = bound
    return result_groups


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
                not 1 <= len(facts['trades']) <= MAX_PINNED_TRADES):
            raise ValueError('facts binding')
    except (OSError, RuntimeError, *DECODE_ERRORS):
        raise StateRefused('owner_external_facts_binding') from None
    return facts


def reconcile(book, packet, *, already_booked=False, sequence=None, collect_inventory=False):
    """Verify the packet against the original book and apply only on an owner-close row."""
    facts, receipts = packet['facts'], packet['receipts']
    fresh = packet.get('schema_version') in FRESH_SCHEMAS
    with_gap = packet.get('schema_version') == GAP_SCHEMA
    if not with_gap and {'additional_activity', 'activity_sha256'}.intersection(packet):
        raise StateRefused('owner_external_activity_binding')
    extras = packet['additional_trades'] if fresh else []
    trades = [*facts['trades'], *extras]
    pinned = {item['receipt']['transaction_hash'] for item in facts['trades']}
    if (facts['schema'] != SCHEMA or packet['facts_sha256'] != digest(facts) or
            facts['anchor_sha256'] != digest(book.inventory_anchor) or
            not 1 <= len(facts['trades']) <= MAX_PINNED_TRADES or len(trades) > MAX_TRADES or
            set(receipts) != {item['receipt']['transaction_hash'] for item in trades} or len(trades) != len(receipts) or
            len({item['source']['trade_id'] for item in trades}) != len(trades)):
        raise StateRefused('owner_external_facts_binding')
    if sum(len(response_bytes(receipt)) for receipt in receipts.values()) > (4_000_000 if fresh else 512_000):
        raise StateRefused('owner_external_receipt_budget')
    wallet = book.ledger.rows[0]['maker_address'].lower()
    bands = attempt_bands(book.ledger, facts['attempt_id'])
    markets = campaign_conditions(book.ledger, sequence) if fresh else {band['start']['condition_id'] for band in bands}
    owned = {row['token_id'] for row in book.ledger.rows[:sequence] if row['event'] == 'leg_intent'} if fresh else book.ledger.tokens()
    order_ids = ({row['order_id'] for row in book.ledger.rows[:sequence] if row['event'] in ('leg_ack', 'leg_adopt')}
                 if fresh else book.ledger.our_order_ids())
    projected = expected_inventory(book.ledger, book.inventory_anchor, book, cut=sequence)
    deltas, cash, personal, gap_blocks = Counter(), 0, [], []
    inventory_contracts = {}
    if fresh:
        anchor = utc(book.inventory_anchor['snapshot_at_utc'])
        cut = utc(packet['coverage_utc'])
        if cut < utc(facts['coverage_utc']) or any(
                not anchor < utc(item['source']['matched_at']) <= cut - timedelta(seconds=1) for item in trades):
            raise StateRefused('owner_external_facts_binding')
        if not with_gap:
            validate_protocol_movements(book, wallet, anchor, cut, packet['protocol_movements'])
    for item in trades:
        source, expected = item['source'], item['receipt']
        tx = expected['transaction_hash']
        if (source['condition_id'] in markets or source['token_id'] in owned or
                source['trade_id'] in order_ids or source['order_id'] in order_ids):
            raise StateRefused('owner_external_campaign_overlap')
        if tx in book.activity_transactions.values():
            raise StateRefused('owner_external_trade_already_booked')
        observed = receipt_facts(wallet, tx, source, receipts[tx], improvement=fresh and tx not in pinned,
                                 inventory_contracts=inventory_contracts)
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
    if with_gap:
        from weather.market.lfc_owner_close_activity import MERGES, apply as apply_gap, prove as prove_gap

        groups = packet['additional_activity']
        finish = max(utc(band['end']['recorded_at_utc']) for band in bands)
        protocol = gap_sources(book, facts, [], cut, packet['protocol_movements'],
                               retained=groups if already_booked else ())
        embedded = {tx: group['rows'] for tx, group in groups.items() if any(row['type'] in MERGES for row in group['rows'])}
        if not groups or protocol != embedded:
            raise StateRefused('owner_external_activity_binding')
        gap, decoded, gap_deltas = prove_gap(book, groups, wallet=wallet,
            markets={str(market).lower() for market in markets}, owned=owned,
            trade_hashes=set(receipts), finish=finish, cut=cut, already_booked=already_booked,
            inventory_contracts=inventory_contracts)
        if collect_inventory and not already_booked:
            packet['activity_sha256'] = digest(gap)
        if packet.get('activity_sha256') != digest(gap):
            raise StateRefused('owner_external_activity_binding')
        deltas.update(gap_deltas)
        cash += sum(item['cash_in_native'] - item['cash_out_native'] for item in gap.values())
        gap_blocks = [item['block_number'] for item in gap.values()]
    if not already_booked:
        for token, delta in deltas.items():
            projected[token] = str(quantity(projected.get(token, 0)) + delta)
    positions = packet['positions']
    from weather.market.lfc_owner_external_inventory import INDEX_OMISSION_LIMIT, collect_checkpoints, native_corrections
    omitted = {}
    for token in set(projected) | set(positions) | set(deltas):
        before, after = projected.get(token, 0), positions.get(token, 0)
        expected = Decimal(before)
        if (fresh and token in deltas and token not in owned and token not in positions and
                -POSITION_DUST < expected < INDEX_OMISSION_LIMIT):
            contracts = inventory_contracts[token]
            if len(contracts) != 1:
                raise StateRefused('owner_external_native_inventory_binding')
            omitted[token] = (expected - deltas[token], deltas[token], next(iter(contracts)))
            continue
        if expected < 0:
            raise StateRefused('owner_external_inventory_changed')
        equal = same_position(before, after) if token in owned else expected == quantity(after)
        if not equal:
            raise StateRefused('owner_external_inventory_changed')
    if packet['cash_native'] != book.expected_cash() + (0 if already_booked else cash):
        raise StateRefused('owner_external_cash_changed')
    corrections = {}
    if omitted:
        trade_blocks = [observed['block_number'] for _, _, observed, _ in personal] + gap_blocks
        if collect_inventory:
            packet['native_inventory'] = collect_checkpoints(wallet, anchor, cut, omitted, min(trade_blocks))
        corrections = native_corrections(packet['native_inventory'], wallet, anchor, cut, omitted, trade_blocks)
    elif 'native_inventory' in packet:
        raise StateRefused('owner_external_native_inventory_binding')
    if sequence is None:
        return
    for token, correction in sorted(corrections.items()):
        if correction:
            book.owner_inventory_adjustments.append({'activity_id': 'owner-native-anchor-' + facts['incident_id'],
                'sequence': sequence, 'token_id': token, 'delta': str(correction), 'read_sha256': packet['read_sha256']})
    for key, source, observed, delta in personal:
        timestamp = utc(source['matched_at']).timestamp()
        book.personal_trades[key] = {'id': key, 'order_id': source['order_id'],
            'timestamp': timestamp, 'side': source['side'],
            'cash_native': observed['gross_native'], 'fee_native': observed['fee_native'],
            'source_sha256': digest(source), **({'sdk_source': source,
                 'receipt_transaction_hash': observed['transaction_hash']} if fresh else {})}
        book.owner_inventory_adjustments.append({'activity_id': 'personal-' + key, 'sequence': sequence,
            'token_id': source['token_id'], 'delta': str(delta), 'read_sha256': packet['read_sha256']})
        signed = observed['cash_in_native'] - observed['cash_out_native']
        if source['side'] == 'BUY':
            book.pool_movements.append({'kind': 'owner_close_debit', 'owner_close_trade': key,
                                        'amount': -signed, 'timestamp': timestamp, 'sequence': sequence})
            book.pools_dirty = True
        else:
            # The receipt proves a single net owner credit even when the fee
            # has its own cash leg. It cannot debit any pre-existing gains.
            move = book.credit('external', signed, {'id': 'personal-' + key, 'timestamp': timestamp},
                               sequence=sequence, owner_cash_native=signed)
            move['owner_close_trade'] = key
        book.cash_in += observed['cash_in_native']
        book.cash_out += observed['cash_out_native']
    book.owner_external_close_cash += sum(observed['cash_in_native'] - observed['cash_out_native']
                                           for _, _, observed, _ in personal)
    gap_allocations = apply_gap(book, groups, gap, decoded, sequence, packet['read_sha256']) if with_gap else []
    book.refresh_pools()
    return {key: book.owner_close_allocations[key] for key in [*(part[0] for part in personal), *gap_allocations]}


def observed_inputs(book, read, facts, *, fresh=False, allow_gap=False):
    cut = utc(facts['coverage_utc'])
    observed_cut = coverage(read)
    rows = retained_activity(book.ledger, read)
    if fresh and not allow_gap:
        refuse_movements(rows, utc(book.inventory_anchor['snapshot_at_utc']),
                         set(book.activity_transactions.values()))
    elif allow_gap:
        finish = max(utc(band['end']['recorded_at_utc']) for band in attempt_bands(book.ledger, facts['attempt_id']))
        historical = [row for row in rows if row['timestamp'] <= finish.timestamp()]
        refuse_movements(historical, utc(book.inventory_anchor['snapshot_at_utc']),
                         set(book.activity_transactions.values()))
    activity_matches = digest(sorted(rows, key=digest)) == facts['activity_sha256']
    if allow_gap and not activity_matches:
        historical = [row for row in rows if row['timestamp'] <= int(cut.timestamp())]
        activity_matches = digest(sorted(historical, key=digest)) == facts['activity_sha256']
    if fresh and not allow_gap and not activity_matches:
        refuse_movements(rows, utc(book.inventory_anchor['snapshot_at_utc']), set())
    if observed_cut < cut or not activity_matches:
        raise StateRefused('owner_external_activity_cut')
    if any(set(item) != {'native_group_sha256'} for item in
           read['capital_activity'].get('pending_native', {}).get('native_receipts', {}).values()):
        raise StateRefused('owner_external_pending_native_changed')
    sources = normalized_sources(book, read, facts['attempt_id'], observed_cut if fresh else cut, fresh=fresh)
    expected = {item['receipt']['transaction_hash']: item['source'] for item in facts['trades']}
    if (any(sources.get(tx) != source for tx, source in expected.items()) if fresh else sources != expected):
        raise StateRefused('owner_external_trade_set_changed')
    cash = native(read['balances']['available_collateral'])
    collateral = [native(value) for asset, value in read['balances']['assets'].items() if asset.lower() == ASSET]
    if collateral != [cash] or str(read['balances']['collateral_evidence']['balance']) != str(cash):
        raise StateRefused('owner_external_collateral_identity')
    observed = {'read_sha256': digest(read), 'positions': normalize_positions(read['positions']), 'cash_native': cash}
    if fresh:
        observed['coverage_utc'] = observed_cut.isoformat()
    return sources, observed, rows


def require_gap_snapshot(read):
    from weather.market.lfc_capital import CapitalRefused
    from weather.market.lfc_f2_inventory import require_stable_snapshot
    try:
        require_stable_snapshot(read)
    except CapitalRefused as exc:
        raise StateRefused('owner_external_activity_cut_retry') from exc


def validate_retained_read(ledger, packet, read, closed_at):
    """Reprove an orphan's saved observations and allocation without fetching anything."""
    from weather.market.lfc_campaign_reads import account_read_age
    from weather.market.lfc_ledger import traded_shares
    if (read.get('schema_version') != 'lfc_campaign_account_read_v0.1' or read.get('complete') is not True or
            read.get('maker_address', '').lower() != ledger.rows[0]['maker_address'].lower() or
            read.get('since') != str(int(utc(ledger.rows[0]['recorded_at_utc']).timestamp())) or
            read.get('scope') != 'account_wide_sdk_trades_and_f0_v2_positions' or read.get('errors') != [] or
            read.get('open_orders') != [] or account_read_age(read, closed_at) > 120 or
            ledger.trade_mismatches(traded_shares(read['trades'], ledger.our_order_ids()))):
        raise StateRefused('owner_close_partial_account_read')
    book = CapitalBook(ledger)
    fresh = packet.get('schema_version') in FRESH_SCHEMAS
    with_gap = packet.get('schema_version') == GAP_SCHEMA
    sources, observed, rows = observed_inputs(book, read, packet['facts'], fresh=fresh, allow_gap=with_gap)
    if any(packet.get(key) != value for key, value in observed.items()):
        raise StateRefused('owner_close_partial_account_read')
    if fresh and sources != {item['receipt']['transaction_hash']: item['source']
                             for item in [*packet['facts']['trades'], *packet['additional_trades']]}:
        raise StateRefused('owner_close_partial_account_read')
    if with_gap:
        require_gap_snapshot(read)
        expected = gap_sources(book, packet['facts'], rows, utc(observed['coverage_utc']), packet['protocol_movements'])
        groups = packet['additional_activity']
        if expected != {tx: proof['rows'] for tx, proof in groups.items()} or any(
                resolve(reference, ledger) != groups[tx] for tx, reference in
                read['capital_activity']['native_receipts'].items() if tx in groups):
            raise StateRefused('owner_close_partial_account_read')
    allocation = reconcile(book, packet, sequence=len(ledger.rows))
    if packet.get('owner_cash_allocation') != allocation:
        raise StateRefused('owner_external_cash_allocation_changed')


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
        old_packet = old['proof']['owner_external_close'] if old is not None else None
        fresh = old_packet is None or old_packet.get('schema_version') in FRESH_SCHEMAS
        allow_gap = old_packet is None or old_packet.get('schema_version') == GAP_SCHEMA
        sources, observed, rows = observed_inputs(book, read, facts, fresh=fresh, allow_gap=allow_gap)
        gaps = {}
        if fresh:
            wallet = ledger.rows[0]['maker_address'].lower()
            anchor = utc(book.inventory_anchor['snapshot_at_utc'])
            cut = utc(observed['coverage_utc'])
            movement = read_protocol_movements(wallet, anchor, cut)
            if allow_gap:
                gaps = gap_sources(book, facts, rows, cut, movement,
                                   retained=() if old_packet is None else old_packet['additional_activity'])
            else:
                validate_protocol_movements(book, wallet, anchor, cut, movement)
        receipts = {tx: rpc_read('eth_getTransactionReceipt', [tx]) for tx in sorted(sources)}
        packet = {'facts': facts, 'facts_sha256': digest(facts), 'receipts': receipts, **observed}
        if fresh:
            pinned = {item['receipt']['transaction_hash'] for item in facts['trades']}
            extras = [{'source': sources[tx], 'receipt': receipt_facts(wallet, tx, sources[tx], receipts[tx], improvement=True)}
                      for tx in sorted(sources.keys() - pinned)]
            packet.update(schema_version=PROOF_SCHEMA, additional_trades=extras, protocol_movements=movement)
            if old_packet is not None and extras != old_packet['additional_trades']:
                raise StateRefused('owner_external_trade_set_changed')
            if gaps:
                require_gap_snapshot(read)
                packet.update(schema_version=GAP_SCHEMA, additional_activity=gap_receipts(book, read, gaps,
                                                                                          reread=old is not None))
            if old_packet is not None and old_packet.get('schema_version') == GAP_SCHEMA:
                if not gaps:
                    raise StateRefused('owner_external_activity_binding')
                packet['activity_sha256'] = old_packet['activity_sha256']
        if old is None:
            packet['owner_cash_allocation'] = reconcile(book, packet, sequence=len(ledger.rows), collect_inventory=True)
        else:
            reconcile(book, packet, already_booked=True, collect_inventory=True)
            packet['owner_cash_allocation'] = old['proof']['owner_external_close'].get('owner_cash_allocation')
    except OSError:
        raise StateRefused('owner_external_receipt_unavailable') from None
    except DECODE_ERRORS as exc:
        raise StateRefused('owner_external_proof_invalid') from exc
    runtime.account_read_preflight(ledger, read)
    book.gate(reserve='0', owner_fault_review=True)
    return {'money_accounting_complete': True, 'cleanup_proven': True, 'unknown_submit': False,
            'money_contradiction': False, 'ledger_head_sha256': ledger.previous, 'read_sha256': digest(read),
            'owner_external_close': packet, 'open_orders': 0}
