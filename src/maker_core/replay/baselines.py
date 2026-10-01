"""Fixed clock control calibrated on exposure only, never on returns or moves."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

from maker_core.replay.engine import replay
from maker_core.replay.score import score


def _fraction(rows):
    covered = sum((r["covered_seconds"] for r in rows), D(0))
    pulled = sum((r["pulled_seconds"] for r in rows), D(0))
    return pulled / covered if covered else None, covered


def matched_clock(bundles, config, target_result, *, check=lambda: None):
    """Match aggregate covered-minute pull fraction to one minute of resolution.

    The calendar pulls a prefix of every declared active interval. A bounded
    bisection selects only the duration, using no price-move, fill-P&L or event
    labels. This is an ex-post exposure-matched descriptive control, not an
    implementable forecast. Safety/coverage/cash may prevent a match; report it
    explicitly and omit that comparator's inferential rows in that case.
    """
    target, covered = _fraction(score(target_result, check=check))
    base = replace(config, policy="clock_only", clock_pulls=())
    result = replay(bundles, base, check=check)
    actual, _ = _fraction(score(result, check=check))
    if target is None or actual is None:
        return result, dict(status="UNMATCHED", target=target, actual=actual, tolerance=None, attempts=1)
    tolerance = min(D(1), D(60) / covered)
    best = abs(actual-target), result, actual, D(0)
    low, high, attempts = D(0), D(1), 1
    for _ in range(12):
        check()
        if best[0] <= tolerance:
            break
        fraction = (low + high) / 2
        windows = []
        for bundle in bundles:
            for c in bundle.conditions:
                seconds = int((c.active_until-c.active_from).total_seconds() * float(fraction))
                if seconds:
                    windows.append((c.condition_id, c.active_from, c.active_from+timedelta(seconds=seconds)))
        trial = replay(bundles, replace(base, clock_pulls=tuple(windows)), check=check)
        got, _ = _fraction(score(trial, check=check))
        attempts += 1
        if got is None:
            break
        if abs(got-target) < best[0]:
            best = abs(got-target), trial, got, fraction
        if got < target:
            low = fraction
        else:
            high = fraction
    error, result, actual, fraction = best
    return result, dict(status="MATCHED" if error <= tolerance else "UNMATCHED", target=target,
                        actual=actual, tolerance=tolerance, absolute_error=error, attempts=attempts,
                        calendar_prefix_fraction=fraction,
                        interpretation="ex-post exposure-matched clock control; no return optimization")
