"""Minimal deterministic as-of policy. Accounting outcomes never enter its interface."""
from datetime import timedelta

from weather.backtesting.t1_types import digest, number, utc


def asof_commands(books, policy, *, start, end, max_age):
    """One fixed pair per predeclared condition at its first available book.

    This deliberately narrow policy has no hindsight eligibility, selection,
    adaptive stops or outcome-dependent cancellation. Other policies remain
    unqualified until their own event runner is implemented and frozen.
    """
    from weather.backtesting.t1_simulator import market_centred_quote

    if policy['kind'] != 'first_book_pair_v1' or type(policy['lifetime_seconds']) is not int or policy['lifetime_seconds'] <= 0:
        raise ValueError('unsupported as-of policy')
    eligible = policy['eligible_conditions']
    if not eligible or len(set(eligible)) != len(eligible):
        raise ValueError('fixed unique policy eligibility required')
    commands, seen = [], set()
    for book in sorted(books, key=lambda b: (utc(b['at']), b['condition_id'])):
        cid = book['condition_id']
        at = utc(book['at'])
        if cid not in eligible or cid in seen or at < utc(start) or at >= utc(end):
            continue
        seen.add(cid)
        expiry = min(at + timedelta(seconds=policy['lifetime_seconds']), utc(end))
        proposals = market_centred_quote(book, condition_id=cid, observed_at=book['at'],
                                         size=policy['size'], distance_cents=policy['distance_cents'],
                                         tick=book['YES']['tick'], expires_at=expiry.isoformat(),
                                         max_book_age_seconds=max_age)
        for command in proposals:
            command.update(decision_book_sha256=digest(book), policy_sha256=digest(policy),
                           decision_available_at=book['at'])
        commands.extend(proposals)
    if set(eligible) != seen:
        raise ValueError('policy has missing first-book evidence; do not remove ineligible dates retrospectively')
    number(policy['size'])
    return commands
