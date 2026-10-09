"""The decision book: one canonical composition of a public book and own resting legs.

Engine ruling W1(a) (spec v3.1 C11) and OD23: ``decide()`` reads the book as the venue would show it with the
caller's own resting legs on it, and computes the qualified mid from that book, own size included (it removes own
size only from the competing reward score and the displayed depth). Every caller that builds a decision book (the
replay v2 kernel and the shadow runner) imports ``compose_book`` from here, so both compute the same book.

Pure: no clock, no I/O, no venue. ``own_size_moves_mid`` is the OD23 shadow diagnostic (count only; it never
changes a decision).
"""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from maker_core.quoting.prices import QuoteRefused, qualified_mid


class UnmergedBookLevels(ValueError):
    """A public book side lists one price twice; the composition refuses to guess how to merge it."""


def compose_book(book, legs):
    """The public book plus own resting legs as the venue displays them (engine ruling W1(a)).

    A YES leg (p, s) adds s at p on yes_bids and at 1 - p on no_asks; a NO leg (p, s) adds s at p on no_bids
    and at 1 - p on yes_asks. A level absent from the public book is created; sizes at one price are summed;
    order is bids high-to-low, asks low-to-high. as_of_utc and post_only_available are unchanged. With no legs
    the book is returned unchanged (and an unmerged side is not checked).
    """
    def merged(levels, additions, descending):
        if not additions:
            return levels
        sizes = {}
        for price, size in levels:
            if price in sizes:
                raise UnmergedBookLevels("unmerged_book_levels")
            sizes[price] = size
        for price, size in additions:
            sizes[price] = sizes.get(price, Decimal(0)) + size
        return tuple(sorted(sizes.items(), key=lambda row: row[0], reverse=descending))
    yes = [(leg.price, leg.size) for leg in legs if leg.outcome == "YES"]
    no = [(leg.price, leg.size) for leg in legs if leg.outcome == "NO"]
    return replace(book,
                   yes_bids=merged(book.yes_bids, yes, True),
                   no_asks=merged(book.no_asks, [(1 - p, s) for p, s in yes], False),
                   no_bids=merged(book.no_bids, no, True),
                   yes_asks=merged(book.yes_asks, [(1 - p, s) for p, s in no], False))


def _mid(book, minimum):
    try:
        return qualified_mid(book.yes_bids, book.yes_asks, minimum)
    except QuoteRefused as refused:
        return str(refused)  # "no mid" (and why) is a value; a refusal on one book only is a difference


def own_size_moves_mid(public, decision, minimum) -> bool:
    """OD23 diagnostic: the qualified mid of the decision book differs from the public book's (own size removed).

    A refusal (no qualified mid, crossed) on one book but not the other, or two different refusals, count as a
    difference. ``minimum`` is the reward minimum size ``decide()`` uses (``RewardTerms.min_size``).
    """
    if decision is public:
        return False
    return _mid(public, minimum) != _mid(decision, minimum)


__all__ = ["UnmergedBookLevels", "compose_book", "own_size_moves_mid"]
