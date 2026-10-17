"""Exact money arithmetic for maker replay v2 (registration draft §3 C5).

Every amount that enters a running portfolio total (cash, a resting reserve, held inventory, a fill's
cost, a settlement payout, a factor-weighted exposure) is quantized to 1e-6 pUSD in a context that
traps ``Inexact``. An amount that is not representable at 1e-6 is refused (``inexact_money_amount``),
never rounded, so a running total is a sum of exact terms and equals a fresh recomputation in value
*and* in representation: every quantized amount has exponent -6, so ``str()`` and therefore every
decision digest agree whichever order the terms were added or removed in.

Report sums (rewards, rebates, markouts, cash-hours) are accumulated exactly in the same context
and rounded once, at the end, by ``round_once``: the registration's "divided once per band-day".
"""
from __future__ import annotations

from decimal import (ROUND_HALF_EVEN, Context, Decimal, DivisionByZero, Inexact, InvalidOperation, Overflow,
                     Underflow)

from maker_core.replay.bundle import BundleError

QUANTUM = Decimal("0.000001")
ZERO = Decimal("0.000000")
# 60 digits hold any exact product or sum of 1e-6 amounts this replay can form (a 16-day run's cash is
# far below 10^20); anything that would need rounding raises instead.
EXACT = Context(prec=60, rounding=ROUND_HALF_EVEN, traps=[Inexact, InvalidOperation, Overflow, DivisionByZero,
                                                          Underflow])
# The single permitted rounding: a report quotient, once per band-day/cell, half-even.
_ROUND = Context(prec=60, rounding=ROUND_HALF_EVEN, traps=[InvalidOperation, Overflow, DivisionByZero])


class MoneyError(BundleError):
    """An amount that 1e-6 cannot represent exactly, or arithmetic that would round."""


def q(value) -> Decimal:
    """Quantize to 1e-6 pUSD; refuse an amount that is not exactly representable there."""
    try:
        return EXACT.quantize(Decimal(value) if not isinstance(value, Decimal) else value, QUANTUM)
    except (Inexact, InvalidOperation, Overflow, Underflow) as exc:
        raise MoneyError("inexact_money_amount") from exc


def add(a: Decimal, b: Decimal) -> Decimal:
    try:
        return EXACT.add(a, b)
    except (Inexact, InvalidOperation, Overflow, Underflow) as exc:
        raise MoneyError("inexact_money_sum") from exc


def sub(a: Decimal, b: Decimal) -> Decimal:
    try:
        return EXACT.subtract(a, b)
    except (Inexact, InvalidOperation, Overflow, Underflow) as exc:
        raise MoneyError("inexact_money_sum") from exc


def mul(a, b) -> Decimal:
    """Exact product (no quantization): the caller quantizes with ``q`` when it is money."""
    try:
        return EXACT.multiply(Decimal(a) if not isinstance(a, Decimal) else a,
                              Decimal(b) if not isinstance(b, Decimal) else b)
    except (Inexact, InvalidOperation, Overflow, Underflow) as exc:
        raise MoneyError("inexact_money_product") from exc


def total(values) -> Decimal:
    """Exact sum of 1e-6 amounts, quantized (a recomputation's form)."""
    result = ZERO
    for value in values:
        result = add(result, value)
    return q(result)


def round_once(numerator: Decimal, denominator) -> Decimal:
    """The one rounding a report value takes: ``numerator / denominator`` to 1e-6, half-even."""
    return _ROUND.quantize(_ROUND.divide(numerator, Decimal(denominator)), QUANTUM)
