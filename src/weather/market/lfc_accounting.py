"""Quantity accounting against an immutable baseline; no price or mark inference."""
from decimal import Decimal, InvalidOperation

from weather.market.mm_stage2_hold import digest


def quantity(value):
    if isinstance(value, bool):
        raise ValueError('quantity_boolean')
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError('quantity_unreadable') from None
    if not result.is_finite() or result < 0:
        raise ValueError('quantity_unreadable')
    return result


def inventory_delta(ledger, baseline, current, *, proven_resting=None):
    """All tokens, including pilot holdings and microfills, must reconcile.

    No automatic redemption/merge/sale inference. A missing API row is an
    unproved holding, including one below the API visibility floor; it never
    becomes an exact zero by tolerance or by observing a marked wallet value.
    """
    if baseline.get('kind') in {'f2_inventory_anchor', 'f2_session_anchor'}:
        from weather.market.lfc_capital import CapitalBook
        from weather.market.lfc_f2_inventory import inventory
        book = CapitalBook(ledger)
        if book.inventory_anchor != baseline:
            raise ValueError('inventory_baseline_or_terminal_missing')
        unresolved = ledger.unresolved_legs()
        resting = frozenset() if proven_resting is None else frozenset(proven_resting)
        if (resting != {leg['order_id'] for leg in unresolved} or
                unresolved and (proven_resting is None or any(quantity(leg['size_matched']) for leg in unresolved))):
            raise ValueError('inventory_baseline_or_terminal_missing')
        return inventory(ledger, baseline, current, book)
    matches = [r for r in ledger.baselines if r['sha256'] == digest(baseline)]
    resting = frozenset() if proven_resting is None else frozenset(proven_resting)
    unresolved = ledger.unresolved_legs()
    if (not matches or (unresolved and (proven_resting is None or
            any(leg['order_id'] not in resting or quantity(leg['size_matched']) != 0 for leg in unresolved))) or
            resting != {leg['order_id'] for leg in unresolved}):
        raise ValueError('inventory_baseline_or_terminal_missing')
    cut = matches[0]['sequence']
    settled_before = {r['order_id']: quantity(r['size_matched']) for r in ledger.rows[:cut]
                      if r['event'] == 'leg_terminal'}
    expected = {str(t): quantity(v) for t, v in baseline['positions'].items() if quantity(v)}
    for oid, key in ledger.by_order.items():
        leg = ledger.legs[key]
        delta = quantity(leg['size_matched']) - settled_before.get(oid, Decimal(0))
        if delta < 0:
            raise ValueError('inventory_terminal_regression')
        token = leg['token_id']
        expected[token] = expected.get(token, Decimal(0)) + delta
    # F2 only: observed redemption removes quantity, never a price-derived
    # settlement assumption. Legacy/manual histories have no such events.
    if getattr(ledger, 'capital_rows', []):
        from weather.market.lfc_capital import CapitalBook
        from weather.market.mm_stage2_hold import utc
        for removal in CapitalBook(ledger).removal_events:
            if removal['timestamp'] < utc(baseline['at_utc']).timestamp():
                continue
            token = removal['token_id']
            expected[token] = expected.get(token, Decimal(0)) - quantity(removal['quantity'])
            if expected[token] < 0:
                raise ValueError('inventory_redemption_scope')
    observed = {str(t): quantity(v) for t, v in current.items() if quantity(v)}
    expected = {t: v for t, v in expected.items() if v}
    changed = sorted(t for t in set(expected) | set(observed) if expected.get(t) != observed.get(t))
    return {'expected': {t: str(v) for t, v in expected.items()}, 'changed': changed,
            'missing_or_below_visibility': sorted(t for t in expected if t not in observed)}
