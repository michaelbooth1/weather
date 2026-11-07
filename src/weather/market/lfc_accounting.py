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


def inventory_delta(ledger, baseline, current):
    """All tokens, including pilot holdings and microfills, must reconcile.

    No automatic redemption/merge/sale inference. A missing API row is an
    unproved holding, including one below the API visibility floor; it never
    becomes an exact zero by tolerance or by observing a marked wallet value.
    """
    matches = [r for r in ledger.baselines if r['sha256'] == digest(baseline)]
    if not matches or ledger.unresolved_legs():
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
    observed = {str(t): quantity(v) for t, v in current.items() if quantity(v)}
    expected = {t: v for t, v in expected.items() if v}
    changed = sorted(t for t in set(expected) | set(observed) if expected.get(t) != observed.get(t))
    return {'expected': {t: str(v) for t, v in expected.items()}, 'changed': changed,
            'missing_or_below_visibility': sorted(t for t in expected if t not in observed)}
