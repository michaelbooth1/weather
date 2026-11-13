"""F2 wallet snapshots at enrollment and between fully closed sessions.

Anchors bind one complete account observation and a ledger cut. Campaign lots,
gains, losses and the funding ceiling continue on the existing capital book.
"""
from decimal import Decimal
import re

from weather.market.lfc_accounting import quantity, same_position, below_position
from weather.market.mm_stage2_hold import digest, utc


PERSONAL_TRADES_RULE = ('Personal trades: only when status is idle, outside run hours; '
                       'none while a session is open; no open orders at 09:00.')
ACTIVITY_OVERLAP_SECONDS = 1800  # Twice the 15-minute mismatch grace.


def filled_totals(ledger, cut):
    totals = {}
    for row in ledger.rows[:cut]:
        if row['event'] == 'leg_terminal':
            token = ledger.legs[ledger.by_order[row['order_id']]]['token_id']
            totals[token] = totals.get(token, Decimal(0)) + quantity(row['size_matched'])
    return {token: str(size) for token, size in totals.items() if size}


def campaign_tokens(ledger, cut=None):
    rows = ledger.rows if cut is None else ledger.rows[:cut]
    return {str(row['token_id']) for row in rows if row['event'] == 'leg_intent'}


def lot_quantities(book, cut):
    totals = {}
    for lot in book.lots.values():
        if lot['terminal_sequence'] < cut:
            token = lot['token_id']
            totals[token] = totals.get(token, Decimal(0)) + lot['remaining_quantity']
    return {token: str(size) for token, size in totals.items() if size}


def outside_removed(book):
    totals = {}
    for row in book.removal_events:
        token = row['token_id']
        totals[token] = totals.get(token, Decimal(0)) + quantity(row['outside_quantity'])
    return {token: str(size) for token, size in totals.items() if size}


def expected_inventory(ledger, anchor, book, *, cut=None):
    expected = {token: quantity(size) for token, size in anchor['positions'].items()}
    totals = filled_totals(ledger, len(ledger.rows) if cut is None else cut)
    before = anchor['filled_totals']
    for token in set(totals) | set(before):
        change = quantity(totals.get(token, 0)) - quantity(before.get(token, 0))
        if change < 0:
            raise ValueError('inventory_terminal_regression')
        expected[token] = expected.get(token, Decimal(0)) + change
    for token in set(book.removed) | set(anchor['removed_totals']):
        change = book.removed.get(token, Decimal(0)) - quantity(anchor['removed_totals'].get(token, 0))
        expected[token] = expected.get(token, Decimal(0)) - change
    for adjustment in getattr(book, 'owner_inventory_adjustments', ()):
        if adjustment['sequence'] >= anchor['ledger_cut']:
            token = adjustment['token_id']
            expected[token] = expected.get(token, Decimal(0)) + Decimal(adjustment['delta'])
    if any(size < 0 for size in expected.values()):
        raise ValueError('inventory_redemption_scope')
    return {token: str(size) for token, size in expected.items() if size}


def inventory(ledger, anchor, current, book, *, campaign_only=False, cut=None):
    expected = expected_inventory(ledger, anchor, book, cut=cut)
    observed = {str(token): str(quantity(size)) for token, size in current.items() if quantity(size)}
    tokens = set(expected) | set(observed)
    if campaign_only:
        tokens &= campaign_tokens(ledger, cut) | set(anchor['campaign_tokens'])
    changed = sorted(token for token in tokens
                     if not same_position(expected.get(token, 0), observed.get(token, 0)))
    return {'expected': expected, 'changed': changed,
            'missing_or_below_visibility': sorted(token for token in tokens if token in expected and token not in observed)}


def require_closed(ledger, read, *, cut=None):
    from weather.market.lfc_capital import CapitalRefused
    if ledger.open_sessions():
        raise CapitalRefused('f2_anchor_open_session')
    if ledger.unacknowledged_intents():
        raise CapitalRefused('f2_anchor_unknown_submit')
    if ledger.unresolved_legs():
        raise CapitalRefused('f2_anchor_unresolved_legs')
    if not between_sessions(ledger, cut=cut):
        raise CapitalRefused('f2_anchor_postchecks_pending')
    if read.get('complete') is not True or read.get('errors', []) != []:
        raise CapitalRefused('f2_anchor_account_incomplete')
    if read.get('open_orders') != []:
        raise CapitalRefused('foreign_open_order')


def enrollment_inventory(book, current, *, cut=None):
    """Every campaign holding must survive even if unrelated holdings changed."""
    expected = lot_quantities(book, len(book.ledger.rows) if cut is None else cut)
    changed = sorted(token for token, size in expected.items()
                     if below_position(current.get(token, 0), size))
    return {'expected': expected, 'changed': changed,
            'missing_or_below_visibility': sorted(token for token in expected if token not in current)}


def require_stable_snapshot(read):
    """Retry a read that already sees a cash event inside its snapshot interval."""
    from weather.market.lfc_capital import CapitalRefused
    times = read.get('component_times', {})
    first = min((utc(times.get(name, {}).get('started_at_utc', read['started_at_utc']))
                 for name in ('positions', 'balances')))
    last = max((utc(times.get(name, {}).get('ended_at_utc', read['ended_at_utc']))
                for name in ('positions', 'balances')))
    packet = read['capital_activity']
    if (int(last.timestamp()) > packet['scope']['end'] or
            utc(read['ended_at_utc']) > first and
            any(source['timestamp'] >= int(first.timestamp()) for source in packet['rows'])):
        raise CapitalRefused('f2_anchor_snapshot_pending')


def make_anchor(book, read, *, kind):
    from weather.market.lfc_capital import CapitalRefused, native
    from weather.market.lfc_ledger import normalize_positions
    require_closed(book.ledger, read)
    positions = {token: str(size) for token, size in normalize_positions(read['positions']).items() if quantity(size)}
    checked = anchor_campaign_check(book, positions, enrollment=kind == 'f2_inventory_anchor')
    if checked['changed']:
        raise CapitalRefused('capital_inventory_unreconciled' if kind == 'f2_session_anchor' else
                             'f2_anchor_campaign_inventory')
    cut = len(book.ledger.rows)
    component_times = read.get('component_times', {})
    snapshot_at = min((component_times.get(name, {}).get('started_at_utc', read['started_at_utc'])
                       for name in ('positions', 'balances')), key=utc)
    covered = min(int(utc(snapshot_at).timestamp()), read['capital_activity']['scope']['end'])
    from weather.market.lfc_f2_personal_cash import sources
    return {'kind': kind, 'maker_address': read['maker_address'].lower(),
            'at_utc': read['ended_at_utc'], 'read_sha256': digest(read),
            'snapshot_at_utc': snapshot_at, 'activity_covered_through': covered,
            'cash_snapshot_at_utc': component_times.get('balances', {}).get('started_at_utc', read['started_at_utc']),
            'activity_scope': read['capital_activity']['scope'],
            'activity_sha256': digest(read['capital_activity']),
            'personal_trade_sources': sources(book, read, snapshot_at),
            'positions': positions, 'positions_sha256': digest(positions),
            'ledger_cut': cut, 'ledger_head_sha256': book.ledger.previous,
            'filled_totals': filled_totals(book.ledger, cut),
            'removed_totals': {token: str(size) for token, size in book.removed.items() if size},
            'outside_removed_totals': outside_removed(book),
            'campaign_tokens': sorted(campaign_tokens(book.ledger, cut)),
            'campaign_quantities': lot_quantities(book, cut),
            'cash_native': native(read['balances']['available_collateral']),
            'complete': True, 'open_orders': []}


def validate_anchor(book, anchor, row, *, enrollment=False):
    """Replay checks the same quantities and cut before accepting any reference."""
    from weather.market.lfc_capital import CapitalRefused
    ledger = book.ledger
    require_closed(ledger, anchor, cut=row['sequence'])
    cut = row['sequence']
    tokens = campaign_tokens(ledger, cut)
    expected_lots = lot_quantities(book, cut)
    valid = (anchor.get('kind') == ('f2_inventory_anchor' if enrollment else 'f2_session_anchor') and
             anchor.get('ledger_cut') == cut and anchor.get('ledger_head_sha256') == row['previous_sha256'] and
             anchor.get('maker_address') == ledger.rows[0]['maker_address'].lower() and
             anchor.get('positions_sha256') == digest(anchor['positions']) and
             anchor.get('filled_totals') == filled_totals(ledger, cut) and
             anchor.get('removed_totals') == {token: str(size) for token, size in book.removed.items() if size} and
             anchor.get('outside_removed_totals') == outside_removed(book) and
             anchor.get('campaign_tokens') == sorted(tokens) and anchor.get('campaign_quantities') == expected_lots and
             type(anchor.get('cash_native')) is int and anchor['cash_native'] >= 0 and
             isinstance(anchor.get('read_sha256'), str) and re.fullmatch('[0-9a-f]{64}', anchor['read_sha256']) is not None and
             0 <= (utc(row['recorded_at_utc']) - utc(anchor['at_utc'])).total_seconds() <= 120)
    if not valid or enrollment and book.inventory_anchor is not None:
        raise CapitalRefused('f2_anchor_binding')
    if 'activity_covered_through' in anchor:
        covered, scope = anchor['activity_covered_through'], anchor['activity_scope']
        if (type(covered) is not int or not 0 < scope['start'] <= covered <= scope['end'] <= int(utc(anchor['at_utc']).timestamp()) or
                covered != min(int(utc(anchor['snapshot_at_utc']).timestamp()), scope['end']) or
                utc(anchor['snapshot_at_utc']) > utc(anchor['at_utc']) or
                re.fullmatch('[0-9a-f]{64}', anchor.get('activity_sha256', '')) is None or
                not isinstance(anchor.get('personal_trade_sources'), list)):
            raise CapitalRefused('f2_anchor_activity_binding')
    checked = anchor_campaign_check(book, anchor['positions'], enrollment=enrollment, cut=cut)
    if checked['changed']:
        raise CapitalRefused('f2_anchor_campaign_inventory')


def anchor_campaign_check(book, positions, *, enrollment, cut=None):
    cut = len(book.ledger.rows) if cut is None else cut
    if enrollment:
        return enrollment_inventory(book, positions, cut=cut)
    if book.inventory_anchor is not None:
        return inventory(book.ledger, book.inventory_anchor, positions, book, campaign_only=True, cut=cut)
    # Retained pre-B080 bridges still use their old accounting anchor until
    # their first session-start snapshot. Their campaign quantities stay exact.
    from weather.market.lfc_capital import prefix_inventory
    expected = prefix_inventory(book.ledger, book.anchor, cut)
    tokens = campaign_tokens(book.ledger, cut)
    changed = sorted(token for token in tokens
                     if quantity(expected.get(token, 0)) != quantity(positions.get(token, 0)))
    return {'expected': expected, 'changed': changed,
            'missing_or_below_visibility': sorted(token for token in tokens if token in expected and token not in positions)}


def between_sessions(ledger, *, cut=None):
    rows = ledger.rows if cut is None else ledger.rows[:cut]
    closed = {row['attempt_id'] for row in rows
              if row['event'] in {'autostart_close', 'autostart_no_intent_close'}}
    return (not ledger.open_sessions() and not ledger.unresolved_legs() and
            all(row['attempt_id'] in closed for row in rows if row['event'] == 'autostart_claim'))


def activity_start(ledger, read_started):
    from weather.market.lfc_capital import CapitalBook
    anchor = CapitalBook(ledger).inventory_anchor
    if anchor is not None:
        watermark = anchor.get('activity_covered_through', int(utc(anchor['at_utc']).timestamp()))
    else:
        watermark = int(utc(read_started).timestamp())
    return max(int(utc(ledger.rows[0]['recorded_at_utc']).timestamp()), watermark - ACTIVITY_OVERLAP_SECONDS)


def during_session(ledger, timestamp):
    return any(session['start'].get('autostart_attempt_id') and
               int(utc(session['start']['recorded_at_utc']).timestamp()) <= timestamp and
               (session['end'] is None or timestamp <= int(utc(session['end']['recorded_at_utc']).timestamp()))
               for session in ledger.sessions.values())
