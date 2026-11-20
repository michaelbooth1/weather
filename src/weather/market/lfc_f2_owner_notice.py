"""Receive-only classification for account activity seen on the F2 user stream."""
import re

from weather.market.mm_stage2_hold import digest


NOTICE = 'account_external_activity_notice'
OVERLAP = 'account_external_campaign_overlap'
TYPES = {'trade', 'auto_redeem', 'redeem', 'deposit', 'withdrawal', 'reward', 'yield',
         'rebate', 'maker_rebate', 'taker_rebate', 'referral_reward', 'merge',
         'directional_merge', 'tip', 'order'}
HASH = re.compile(r'0x[0-9a-f]{64}', re.I)


def scope(ledger, cut=None):
    rows = ledger.rows if cut is None else ledger.rows[:cut]
    starts = [row for row in rows if row['event'] == 'session_start']
    intents = [row for row in rows if row['event'] == 'leg_intent']
    conditions = {str(row['condition_id']).lower() for row in starts + intents if row.get('condition_id')}
    tokens = {row['token_id'] for row in intents}
    for row in starts:
        tokens.update(row.get('f2_owner_activity_tokens', ()))
    return conditions, tokens


def classify(item, *, wallet, registry, known_scope):
    """A notice carries no authority to credit cash, retire an order or apply a fill."""
    if not isinstance(item, dict):
        return None
    kind = str(item.get('event_type', '')).lower()
    if kind not in TYPES:
        return None
    market = str(item.get('market') or item.get('condition_id') or '').lower()
    conditions, tokens = known_scope()
    conditions = conditions | set(registry)
    tokens = tokens | {token for reader in registry.values() for token in reader.tokens}
    if kind == 'trade':
        parts = item.get('maker_orders', [])
        if not isinstance(parts, list) or any(not isinstance(row, dict) for row in parts):
            return None
        own = [part for part in parts if str(part.get('maker_address', '')).lower() == wallet]
        # Own taker messages report the account as proxy_wallet or maker_address.
        top_own = any(str(item.get(key, '')).lower() == wallet for key in ('proxy_wallet', 'maker_address'))
        if not (own or top_own) or not HASH.fullmatch(market):
            return None
        orders = {item.get('taker_order_id'), *(part.get('order_id') for part in parts)}
        known = {oid for reader in registry.values() for oid in reader.known_order_ids.copy()}
        peer = registry.get(market)
        if peer is not None and own and all(part.get('asset_id', part.get('token_id')) in peer.tokens for part in own):
            # An exact-band maker event can beat its POST acknowledgement.
            # The normal fill handler binds it to the order and the REST proof
            # still rejects mixed or non-campaign executions in this market.
            return None
        if str(item.get('status', '')).upper() not in {'MATCHED', 'MINED', 'CONFIRMED', 'RETRYING', 'FAILED'}:
            return None
        if not isinstance(item.get('id'), str) or not item['id']:
            return None
        affected = {str(row.get('asset_id', row.get('token_id'))) for row in [item, *parts]}
        overlap = bool(market in conditions or tokens & affected or orders & known)
    elif kind == 'order':
        if (not any(str(item.get(key, '')).lower() == wallet for key in ('proxy_wallet', 'maker_address')) or
                not HASH.fullmatch(market) or not isinstance(item.get('id'), str) or not HASH.fullmatch(item['id'])):
            return None
        affected = str(item.get('asset_id', item.get('token_id')))
        if market in registry and affected in registry[market].tokens:
            return None  # The normal selected order path handles ACK races.
        overlap = market in conditions or affected in tokens
    else:
        if str(item.get('proxy_wallet', '')).lower() != wallet:
            return None
        tx = item.get('txn_hash') or item.get('transaction_hash') or ''
        if not isinstance(tx, str) or not HASH.fullmatch(tx):
            return None
        if kind in {'auto_redeem', 'redeem', 'merge', 'directional_merge'} and not HASH.fullmatch(market):
            return None
        if any(key in item for key in ('order_id', 'maker_orders', 'taker_order_id')):
            return None
        overlap = market in conditions or str(item.get('asset_id', item.get('token_id'))) in tokens
    if kind == 'trade':
        identity = digest(['trade', item['id']]) if str(item.get('status', '')).upper() != 'FAILED' else None
    elif kind == 'order':
        identity = None  # Reservation and ownership come from the open-order GET.
    else:
        identity = digest(['transaction', tx.lower()])
    return {'event_type': OVERLAP if overlap else NOTICE, 'activity_type': kind,
            'raw_event_sha256': digest(item), 'activity_identity_sha256': identity}
