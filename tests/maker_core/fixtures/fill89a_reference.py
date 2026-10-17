"""Pure pieces of the frozen September 23 fill-toxicity study (not a trader)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import chain
from typing import Callable, Iterable

from weather.market import reward_share_estimate as rewards


WINDOW_MINUTES = {"E1": (3, 10), "E2": (10, 15), "E3": (15, 15),
                  "E4": (5, 30), "E5": (10, 25)}
WINDOW_SETS = {**{key: (key,) for key in WINDOW_MINUTES},
               "E123": ("E1", "E2", "E3"), "ALL": tuple(WINDOW_MINUTES)}
DISTANCES = (1.5, 2.5)
FILL_RULES = ("conservative", "optimistic")
QUOTE_SIZE = 20.0
MAX_QUOTE_AGE = 300.0
MIN_SAMPLE_SPACING = 30.0


class StudyError(ValueError):
    """Refuse an unidentifiable input/contract; never silently change the panel."""


@dataclass(frozen=True)
class Terms:
    captured: float
    rate: float
    minimum: float
    spread: float
    source: str = "condition_record"

    def usable(self, minute: float) -> bool:
        if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in
                   (self.captured, self.rate, self.minimum, self.spread)):
            return False
        return (0 <= minute - self.captured <= 3600 and self.rate >= 0
                and self.minimum >= 0 and self.spread >= 0
                and all(math.isfinite(x) for x in
                        (self.captured, self.rate, self.minimum, self.spread)))


@dataclass(frozen=True)
class Book:
    at: float
    bids: tuple[tuple[float, float], ...]
    asks: tuple[tuple[float, float], ...]
    tick: float


@dataclass(frozen=True)
class Print:
    at: float
    price: float
    size: float


@dataclass(frozen=True)
class Window:
    kind: str
    start: float
    end: float
    observed: float
    detected: float | None = None
    band: str | None = None


def event_window(kind: str, at: float, detected=None, band=None) -> Window:
    pre, post = WINDOW_MINUTES[kind]
    return Window(kind, at - pre * 60, at + post * 60, at, detected, band)


def placebo_windows(windows: list[Window], tz) -> tuple[list[Window], int]:
    """Clarification 1: HH:20, same duration; drop any E1-E5 overlap."""
    result, dropped = [], 0
    for window in windows:
        local = datetime.fromtimestamp(window.observed, timezone.utc).astimezone(tz)
        start = local.replace(minute=20, second=0, microsecond=0).timestamp()
        end = start + window.end - window.start
        if any(start < other.end and other.start < end for other in windows):
            dropped += 1
        else:
            result.append(Window("PLACEBO", start, end, start, band=window.band))
    return result, dropped


def membership(windows: Iterable[Window], at: float, band: str) -> set[str]:
    kinds = {w.kind for w in windows if w.start <= at < w.end
             and (w.band is None or w.band == band)}
    result = {key for key, members in WINDOW_SETS.items() if kinds.intersection(members)}
    if "PLACEBO" in kinds:
        result.add("PLACEBO")
    if "E2_DETECTED" in kinds:
        result.add("E2_DETECTED")
    if kinds.intersection(("E1", "E2_DETECTED", "E3")):
        result.add("E123_DETECTED")
    if "ALL" not in result:
        result.add("OUTSIDE")
    return result


def selected_books(books: Iterable[Book]) -> Iterable[Book]:
    """First capture per UTC minute, then the frozen 30-second spacing filter."""
    previous_at, seen_minute, previous_selected = -math.inf, None, -math.inf
    for book in books:
        if book.at < previous_at:
            raise StudyError("books must be ordered by capture timestamp")
        previous_at = book.at
        minute = int(book.at // 60)
        if minute == seen_minute:
            continue
        seen_minute = minute
        if book.at - previous_selected < MIN_SAMPLE_SPACING:
            continue
        previous_selected = book.at
        yield book


def simulate(
    books: Iterable[Book], prints: Iterable[Print], *, start: float, end: float,
    terms_at: Callable[[float], Terms | None], windows: list[Window], band: str,
    distance: float, rule: str, exposure: Callable[..., None], fill: Callable[..., None],
    diagnostics: dict[str, int], quote_record: Callable[..., None] | None = None,
) -> None:
    """Continuous counterfactual quote, streamed; callbacks retain all intermediates.

    Exposure callback: (start, end, resting_share_minutes, reward_many,
    reward_single, membership, population, remaining_sizes). Fill callback: (time, shares,
    snapped_price, maker_side, membership, population).
    Equal-time prints consume the expiring quote before its replacement; this
    conservative tie rule does not invent an ordering inside a capture timestamp.
    """
    if distance not in DISTANCES or rule not in FILL_RULES:
        raise StudyError("unfrozen quote distance or fill rule")
    book_iter, trade_iter = iter(selected_books(books)), iter(prints)
    book, trade = next(book_iter, None), next(trade_iter, None)
    while book is not None and book.at < start:
        book = next(book_iter, None)
    while trade is not None and trade.at < start:
        trade = next(trade_iter, None)
    boundary = sorted({x for w in windows for x in (w.start, w.end) if start < x < end})
    boundaries = iter(chain(boundary, (end,)))
    window_boundary = next(boundaries)
    at = start
    remaining = [0.0, 0.0]
    prices = [None, None]
    current_book = None
    expiry = end
    population = "midrange"

    def count(key):
        diagnostics[key] = diagnostics.get(key, 0) + 1

    while at < end:
        minute = math.floor(at / 60) * 60
        terms = terms_at(minute)
        if terms is None or not terms.usable(minute):
            remaining = [0.0, 0.0]
        if at >= expiry:
            remaining = [0.0, 0.0]
        # Existing resting quote is exposed to equal-time trades before reprice.
        while trade is not None and trade.at == at:
            for side in (0, 1):
                price = prices[side]
                if price is None or remaining[side] <= 0:
                    continue
                through = trade.price < price if side == 0 else trade.price > price
                qualifies = through or (rule == "optimistic" and trade.price == price)
                if qualifies:
                    size = min(trade.size, remaining[side])
                    remaining[side] -= size
                    fill(at, size, price, "bought" if side == 0 else "sold",
                         membership(windows, at, band), population)
            old_at = trade.at
            trade = next(trade_iter, None)
            if trade is not None and trade.at < old_at:
                raise StudyError("prints must be in venue-timestamp order")
        if book is not None and book.at == at:
            remaining = [0.0, 0.0]
            current_book = book
            expiry = min(end, at + MAX_QUOTE_AGE)
            if terms is not None and terms.usable(minute):
                bid, ask = rewards.best_prices(book.bids, book.asks, terms.minimum)
                if bid is None or ask is None:
                    count("one_sided_samples")
                elif bid >= ask:
                    count("crossed_samples")
                else:
                    mid = (bid + ask) / 2
                    population = "midrange" if 0.10 <= mid <= 0.90 else "outside_midrange"
                    quote = rewards.hypothetical_quote(mid, distance, book.tick)
                    prices = [quote["bid_price"], quote["ask_price"]]
                    remaining = [QUOTE_SIZE if price is not None else 0.0 for price in prices]
                    if quote_record is not None:
                        quote_record(at, {**quote, "midpoint": mid, "tick": book.tick,
                            "target_distance_cents": distance, "size_per_leg": QUOTE_SIZE,
                            "terms": vars(terms)})
                    count(population + "_samples")
            book = next(book_iter, None)
        while window_boundary <= at and window_boundary < end:
            window_boundary = next(boundaries)
        next_at = min(end, minute + 60, window_boundary,
                      book.at if book is not None else end,
                      trade.at if trade is not None else end,
                      expiry if expiry > at else end)
        if next_at <= at:
            raise StudyError("non-advancing simulation clock")
        if sum(remaining) > 0 and terms is not None and current_book is not None:
            bid, ask = rewards.best_prices(current_book.bids, current_book.asks, terms.minimum)
            if bid is None or ask is None or bid >= ask:
                # The minute's updated terms cannot define a valid adjusted book.
                remaining = [0.0, 0.0]
            else:
                mid = (bid + ask) / 2
                comp_one, _ = rewards.side_score(current_book.bids, mid, terms.spread, terms.minimum)
                comp_two, _ = rewards.side_score(current_book.asks, mid, terms.spread, terms.minimum)
                own = [rewards.order_score(size, None if price is None else (price - mid) * 100,
                                           terms.spread, terms.minimum)
                       for size, price in zip(remaining, prices)]
                own_q = rewards.q_min(*own, mid)
                many = rewards.share_of(own_q, (comp_one + comp_two) / 2)
                single = rewards.share_of(own_q, rewards.q_min(comp_one, comp_two, mid))
                duration = (next_at - at) / 60
                exposure(at, next_at, sum(remaining) * duration,
                         terms.rate / 1440 * many * duration,
                         terms.rate / 1440 * single * duration,
                         membership(windows, at, band), population, tuple(remaining))
        at = next_at
