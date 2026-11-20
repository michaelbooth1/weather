"""Open-order scope and pUSD liability. An unrelated order is never ours to cancel."""
import re
from uuid import UUID

from weather.market.lfc_accounting import quantity
from weather.market.lfc_capital import CapitalBook, CapitalRefused, native
from weather.market.lfc_f2_owner_notice import scope
from weather.market.mm_stage2_hold import _order_id


def mark_open_orders(rows, heartbeat_key):
    """Classify in memory and never retain the API-key owner field."""
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise CapitalRefused('foreign_open_order_identity')
    try:
        heartbeat = UUID(heartbeat_key)
    except (TypeError, ValueError, AttributeError):
        heartbeat = None
    clean = []
    for row in rows:
        try:
            owner = UUID(row.get('owner'))
        except (TypeError, ValueError, AttributeError):
            owner = None
        clean.append({**{key: value for key, value in row.items() if key != 'owner'},
                      'heartbeat_key_isolated': heartbeat is not None and owner is not None and owner != heartbeat})
    return clean


def condition(row):
    return str(row.get('market') or row.get('condition_id') or '').lower()


def token(row):
    return str(row.get('asset_id') or row.get('token_id') or '')


def split(ledger, rows, *, selected=()):
    conditions, tokens = scope(ledger)
    conditions.update(row['condition_id'] for row in selected)
    tokens.update(t for row in selected for t in row['token_ids'])
    known, seen = ledger.our_order_ids(), set()
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise CapitalRefused('foreign_open_order_identity')
    campaign, foreign = [], []
    for row in rows:
        oid = _order_id(row)
        if (not re.fullmatch('0x[0-9a-fA-F]{64}', oid) or oid in seen or
                not re.fullmatch('0x[0-9a-fA-F]{64}', condition(row)) or not token(row).isdigit() or
                row.get('market') and row.get('condition_id') and row['market'].lower() != row['condition_id'].lower() or
                row.get('asset_id') and row.get('token_id') and str(row['asset_id']) != str(row['token_id'])):
            raise CapitalRefused('foreign_open_order_identity')
        seen.add(oid)
        (campaign if oid in known or condition(row) in conditions or token(row) in tokens else foreign).append(row)
    return campaign, foreign


def campaign_open_rows(ledger, rows):
    return split(ledger, rows)[0]


def foreign_reserve(ledger, rows, *, require_isolated=True):
    """Round each remaining BUY cost up before comparing integer native units."""
    total = 0
    for row in rows:
        if require_isolated and row.get('heartbeat_key_isolated') is not True:
            raise CapitalRefused('foreign_open_order_heartbeat_scope')
        if (str(row.get('maker_address', '')).lower() != ledger.rows[0]['maker_address'].lower() or
                row.get('side') not in {'BUY', 'SELL'} or str(row.get('status', '')).upper() != 'LIVE'):
            raise CapitalRefused('foreign_open_order_identity')
        try:
            price, size, matched = (quantity(row[key]) for key in ('price', 'original_size', 'size_matched'))
            if not 0 < price < 1 or not 0 <= matched < size:
                raise ValueError()
        except (ArithmeticError, KeyError, TypeError, ValueError) as exc:
            raise CapitalRefused('foreign_open_order_quantity') from exc
        if row['side'] == 'BUY':
            total += native(price * (size - matched), ceil=True)
    return total


def gate(ledger, rows, *, cash, reserve=0, own_resting=0, loss_basis=None, selected=()):
    campaign, foreign = split(ledger, rows, selected=selected)
    if campaign:
        raise CapitalRefused('foreign_open_order_campaign_overlap')
    locked = foreign_reserve(ledger, foreign)
    figures = CapitalBook(ledger).gate(reserve=reserve, available_cash=cash, own_resting=own_resting,
                                       external_resting=locked, loss_basis=loss_basis)
    return figures
