"""Receipt-proved between-session activity carried by one owner-close decision."""
from collections import Counter, defaultdict
from decimal import Decimal

from weather.market.lfc_accounting import quantity
from weather.market.lfc_campaign_state import StateRefused
from weather.market.lfc_capital import SCALE, REWARD_TYPES, native, normalize_activity
from weather.market.lfc_capital_native import hex_number, result, wallet_transfer_totals
from weather.market.lfc_redemption_native import CTF, address, topic, unpack
from weather.market.lfc_recording_io import response_bytes
from weather.market.mm_stage2_hold import digest, utc


MERGE = topic('PositionsMerge(address,address,bytes32,bytes32,uint256[],uint256)')
MERGES = {'MERGE', 'DIRECTIONAL_MERGE'}
TYPES = REWARD_TYPES | MERGES | {'DEPOSIT', 'WITHDRAWAL', 'TIP', 'REDEEM'}
MAX_TRANSACTIONS = 64


def sources(book, rows, finish, cut, *, retained=()):
    from weather.market.lfc_owner_external_close import hash32, refuse_movements

    booked = set(book.activity_transactions.values()) - set(retained)
    anchor = utc(book.inventory_anchor['snapshot_at_utc'])
    groups = defaultdict(list)
    for row in rows:
        tx = str(row['transaction_hash']).lower()
        if tx in booked or row['timestamp'] < int(anchor.timestamp()):
            continue
        if row['timestamp'] <= finish.timestamp() or row['type'] not in TYPES:
            refuse_movements([row], anchor, set())
            raise StateRefused('owner_external_activity_session_overlap')
        if row['timestamp'] + 1 > cut.timestamp():
            raise StateRefused('owner_external_activity_cut_retry')
        groups[hash32(tx)].append(row)
    return dict(groups)


def merge_burns(row, receipt, tx, wallet, incoming, outgoing):
    from weather.market.lfc_owner_external_close import log_index

    logs = [log for log in receipt['logs'] if log['address'].lower() == CTF and log['topics'] and
            log['topics'][0].lower() == MERGE and len(log['topics']) == 4 and
            address(log['topics'][1]) == wallet]
    if len(logs) != 1 or logs[0]['topics'][3].lower() != row['condition_id'].lower():
        raise StateRefused('owner_external_merge_unproved')
    log_index(receipt, logs[0], tx)
    _, partition, amount = unpack(logs[0], 4, ['address', 'uint256[]', 'uint256'])
    if (set(partition) != {1, 2} or len(partition) != 2 or native(row['size']) != amount or
            incoming or len(outgoing) != 2 or set(outgoing.values()) != {amount} or not amount):
        raise StateRefused('owner_external_merge_unproved')
    return outgoing, amount


def prove(book, groups, *, wallet, markets, owned, trade_hashes, finish, cut, already_booked):
    """Decode the same native rows used by ordinary capital reads and bind full wallet legs."""
    from weather.market.lfc_owner_external_close import hash32, wallet_position_moves

    if len(groups) > MAX_TRANSACTIONS:
        raise StateRefused('owner_external_activity_cap')
    if sum(len(response_bytes(packet)) for group in groups.values()
           for packet in (group['receipt'], *group.get('ctf_views', {}).values()) if packet is not None) > 4_000_000:
        raise StateRefused('owner_external_activity_receipt_budget')
    raw = [row for group in groups.values() for row in group['rows']]
    if (sources(book, raw, finish, cut, retained=groups if already_booked else ()) !=
            {tx: g['rows'] for tx, g in groups.items()}):
        raise StateRefused('owner_external_activity_binding')
    facts, decoded, deltas = {}, {}, Counter()
    for tx, group in sorted(groups.items()):
        rows = group['rows']
        kinds = {row['type'] for row in rows}
        if (tx in trade_hashes or group['transaction_hash'] != tx or not rows or len(kinds) != 1 or
                len(rows) != 1 and kinds != {'REDEEM'} or len({row['timestamp'] for row in rows}) != 1 or
                any(row['proxy_wallet'].lower() != wallet or str(row['condition_id']).lower() in markets or
                    str(row['token_id']) in owned for row in rows)):
            raise StateRefused('owner_external_activity_overlap')
        receipt = result(group['receipt'])
        cash = wallet_transfer_totals(receipt, tx, wallet)
        incoming, outgoing = wallet_position_moves(receipt, tx, wallet)
        items = [normalize_activity(row, group) for row in rows]
        ids = {item['id'] for item in items}
        if len(ids) != len(items) or any((item['id'] in book.activities) != already_booked or (
                already_booked and book.activities[item['id']] != item) for item in items):
            raise StateRefused('owner_external_activity_binding')
        item = items[0]
        kind = item['type']
        debit = kind == 'WITHDRAWAL' or kind == 'TIP' and item['direction'] == 'OUT'
        burns = {}
        if kind == 'REDEEM':
            bundle = item.get('native_redemption')
            if not bundle or any(other.get('native_redemption') != bundle for other in items):
                raise StateRefused('owner_external_redemption_unproved')
            burns = {part['token_id']: native(part['quantity']) for part in bundle['positions']}
            if incoming or burns != outgoing:
                raise StateRefused('owner_external_redemption_unproved')
        elif kind in MERGES:
            burns, paid = merge_burns(rows[0], receipt, tx, wallet, incoming, outgoing)
            if paid != item['cash_native']:
                raise StateRefused('owner_external_merge_unproved')
        elif incoming or outgoing:
            raise StateRefused('owner_external_activity_inventory_changed')
        if owned.intersection(burns):
            raise StateRefused('owner_external_campaign_overlap')
        signed = cash['IN'] - cash['OUT']
        allowed_cash = {'IN': 0, 'OUT': -signed} if debit else {'IN': signed, 'OUT': 0}
        if cash != allowed_cash or any(other['cash_native'] != abs(signed) for other in items):
            raise StateRefused('owner_external_activity_cash_unproved')
        deltas.subtract({token: Decimal(amount) / SCALE for token, amount in burns.items()})
        facts[tx] = {'sources': [digest(row) for row in rows], 'receipt': digest(receipt),
            'block_hash': hash32(receipt['blockHash']), 'block_number': hex_number(receipt['blockNumber']),
            'cash_in_native': cash['IN'], 'cash_out_native': cash['OUT'], 'burns_native': burns}
        decoded[tx] = items
    return facts, decoded, deltas


def apply(book, groups, facts, decoded, sequence, read_sha):
    """Apply ordinary reward/owner pools and segregate the entire proved owner debit."""
    allocations = []
    for tx, group in groups.items():
        sha = digest(group)
        if sha not in book.native_groups:
            book.apply({'event': 'capital_native_group', 'proof': group, 'proof_sha256': sha})
        items = decoded[tx]
        item, info = items[0], facts[tx]
        key, kind = item['id'], item['type']
        for raw, observed in zip(group['rows'], items, strict=True):
            ident = observed['id']
            book.seen.add(ident)
            book.activities[ident] = observed
            book.sources[ident] = digest(raw)
            book.activity_sequences[ident] = sequence
            book.activity_transactions[ident] = tx
            book.pending_native_outgoing.discard(ident)
        for token, amount in sorted(info['burns_native'].items()):
            book.owner_inventory_adjustments.append({'activity_id': key, 'sequence': sequence, 'token_id': token,
                'delta': str(-Decimal(amount) / SCALE), 'read_sha256': read_sha})
        if kind == 'REDEEM':
            book.redeemed_transactions[tx] = key
            for observed in items:
                ident = observed['id']
                entry = ({'unallocated': []} if ident == key else {'duplicate_of': key})
                book.redemptions[ident] = {'activity_id': ident, 'cash_native': info['cash_in_native'] if ident == key else 0,
                    'cost_basis_released_native': 0, 'returned_principal_native': 0, 'outside_campaign': True, **entry}
        incoming, outgoing = info['cash_in_native'], info['cash_out_native']
        if outgoing:
            allocation = 'activity-' + key
            allocations.append(allocation)
            book.pool_movements.append({'kind': 'owner_close_debit', 'owner_close_trade': allocation,
                'activity_id': key, 'amount': outgoing, 'timestamp': item['timestamp'], 'sequence': sequence})
            book.pools_dirty = True
        elif kind in REWARD_TYPES:
            book.credit('incentives', incoming, item, sequence=sequence, native_proven=True)
        else:
            book.credit('external', incoming, item, sequence=sequence, native_proven=True, owner_cash_native=incoming)
        book.cash_in += incoming
        book.cash_out += outgoing
    return allocations
