"""Fresh GET proof between fills; final account completion remains stricter.

Only known, exactly bound LIVE orders with zero matched quantity may remain in
other bands. An unacknowledged intent never takes this route. No order mutation,
adoption, incident recovery, baseline advance or principal inference occurs here.
"""
from weather.market.lfc_accounting import quantity
from weather.market.lfc_campaign import TransientPrecheck
from weather.market.lfc_campaign_reads import account_read_age
from weather.market.lfc_capital import CapitalRefused
from weather.market.lfc_ledger import traded_shares
from weather.market.mm_stage2_hold import HoldEnd, digest, exact_open_orders, _order_id, utc


def validate_live(ledger, read, *, attempt, now):
    """Validate the full account before allowing nonterminal inventory inputs."""
    from weather.market.lfc_f2_breadth import PROTOCOL
    if ledger.halted or ledger.mismatches or ledger.unacknowledged_intents():
        raise CapitalRefused('repost_money_unproven')
    sessions = [ledger.sessions[sid]['start'] for sid in ledger.open_sessions()]
    if not sessions or any(s.get('protocol') != PROTOCOL or s.get('autostart_attempt_id') != attempt for s in sessions):
        raise CapitalRefused('repost_attempt_scope')
    if (read.get('complete') is not True or read.get('errors') != [] or
            read.get('maker_address', '').lower() != ledger.rows[0]['maker_address'].lower() or
            account_read_age(read, utc(now)) > 120):
        raise CapitalRefused('repost_account_read_binding')
    unresolved = ledger.unresolved_legs()
    if any(ledger.sessions[leg['session_id']]['start'].get('protocol') != PROTOCOL or
           ledger.sessions[leg['session_id']]['start'].get('autostart_attempt_id') != attempt for leg in unresolved):
        raise CapitalRefused('repost_attempt_scope')
    expected = {leg['order_id']: leg for leg in unresolved}
    rows = read.get('open_orders')
    if (not isinstance(rows, list) or len(rows) != len(expected) or
            {_order_id(row) for row in rows} != set(expected)):
        raise TransientPrecheck('repost_open_orders_unproven')
    orders = read.get('terminal_orders')
    if not isinstance(orders, dict) or set(orders) != set(expected):
        raise CapitalRefused('repost_order_read_coverage')
    since, end = utc(read['started_at_utc']), utc(read['ended_at_utc'])
    for condition in {leg['condition_id'] for leg in unresolved}:
        scoped = {oid: (leg['token_id'], quantity(leg['price']), quantity(leg['size']))
                  for oid, leg in expected.items() if leg['condition_id'] == condition}
        try:
            exact_open_orders([row for row in rows if _order_id(row) in scoped], scoped,
                              maker=ledger.rows[0]['maker_address'], condition=condition)
            fresh = []
            for oid in scoped:
                packet = orders[oid]
                first, last = utc(packet['started_at_utc']), utc(packet['ended_at_utc'])
                if not since <= first <= last <= end or (utc(now) - first).total_seconds() > 120:
                    raise CapitalRefused('repost_order_read_age')
                fresh.append(packet['row'])
            exact_open_orders(fresh, scoped, maker=ledger.rows[0]['maker_address'], condition=condition)
        except HoldEnd as exc:
            raise TransientPrecheck('repost_live_order_unproven') from exc
    traded = traded_shares(read['trades'], ledger.our_order_ids())
    if any(quantity(traded.get(oid, 0)) for oid in expected):
        raise TransientPrecheck('repost_peer_fill_pending')
    if ledger.trade_mismatches(traded):
        raise TransientPrecheck('repost_terminal_trades_unproven')
    return set(expected)


def prove(runtime, band, read):
    """This proof permits another quote; it never claims account cleanup PASS."""
    ledger = band.ledger
    runtime.validate_account_read(ledger, read)
    validate_live(ledger, read, attempt=band.venue.coordinator.attempt_id, now=runtime.clock.now())
    from weather.market.lfc_f2_repost import private_fill_proof
    for peer in band.venue.coordinator.bands:
        private_fill_proof(peer, require_terminal=peer is band)
    from weather.market.lfc_capital_reads import synchronize
    capital = synchronize(ledger, runtime.original_baseline(ledger), read,
                          live_proof={'attempt_id': band.venue.coordinator.attempt_id})
    if capital.get('cash_bridge_complete') is not True:
        raise CapitalRefused('repost_cash_bridge_unproven')
    ids = {str(row['id']) for row in read['trades'] if row.get('id') is not None}
    if not band.observed_trade_ids <= ids:
        raise TransientPrecheck('repost_stream_fill_unproven')
    return {'inventory_proven': True, 'unknown_submit': False, 'cleanup_proven': False,
            'read_sha256': digest(read), 'ledger_head_sha256': ledger.previous,
            'proven_trade_ids': sorted(ids), 'capital': capital}
