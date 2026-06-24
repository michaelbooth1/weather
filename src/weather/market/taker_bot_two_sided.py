"""Two-sided (NO-side) taker helpers (item 253).

The taker historically buys only the YES token of an **under**-priced band and
ignores the symmetric case where the model thinks a band is **over**-priced,
where buying the NO token has positive expected value. These helpers:

1. capture the NO-token book for a band (a real captured NO book when present,
   otherwise the no-arbitrage complement of the YES book), and
2. synthesize a NO-side candidate input row (``fair`` becomes ``1 - fair_yes``,
   the book becomes the NO book, the traded token becomes the NO token) so it
   flows through the *existing* YES decision/gate pipeline unchanged.

NO-side settlement is inverted: a NO buy on band ``X`` wins when the settlement
is **not** in band ``X`` (``no_buy_settlement_outcome``).

By no-arbitrage on a binary YES/NO pair, buying NO is selling YES, so:
``no_ask = 1 - yes_bid`` and ``no_bid = 1 - yes_ask``.
"""

from weather.market.taker_bot_tape_io import (
    clamp_probability,
    compact_float,
    first_present,
    maybe_float,
)

NO_SIDE = "NO_BUY"
YES_SIDE = "YES_BUY"


def order_side(row):
    return str((row or {}).get("side") or (row or {}).get("taker_side") or YES_SIDE).upper()


def no_token_id(row):
    token = str((row or {}).get("clob_no_token_id") or "").strip()
    return token or None


def no_book_fields(row):
    """Return NO-token book fields for ``row``.

    Prefers a captured NO-token book (``no_best_ask`` / ``no_best_bid`` /
    ``no_ask_size_at_best``); otherwise falls back to the no-arbitrage complement
    of the YES book. ``no_book_source`` records which path was used.
    """
    captured_ask = clamp_probability(first_present(row, "no_best_ask", "clob_no_best_ask"))
    if captured_ask is not None:
        captured_bid = clamp_probability(first_present(row, "no_best_bid", "clob_no_best_bid"))
        ask_size = maybe_float(first_present(row, "no_ask_size_at_best", "no_ask_size", "clob_no_ask_size_at_best"))
        bid_size = maybe_float(first_present(row, "no_bid_size_at_best", "clob_no_bid_size_at_best"))
        ask_depth_1pct = maybe_float(first_present(row, "no_ask_depth_1pct", "clob_no_ask_depth_1pct"))
        age = maybe_float(first_present(row, "no_book_age_seconds", "clob_no_book_age_seconds"))
        return {
            "no_best_bid": compact_float(captured_bid),
            "no_best_ask": compact_float(captured_ask),
            "no_bid_size_at_best": compact_float(bid_size),
            "no_ask_size_at_best": compact_float(ask_size),
            "no_ask_depth_1pct": compact_float(ask_depth_1pct),
            "no_book_source": "no_token_book",
            "no_book_captured_at_utc": first_present(row, "no_book_captured_at_utc", "clob_no_book_captured_at_utc") or "",
            "no_book_age_seconds": compact_float(age),
        }
    yes_bid = clamp_probability(first_present(row, "clob_best_bid", "best_bid", "gamma_best_bid"))
    yes_ask = clamp_probability(first_present(row, "clob_best_ask", "best_ask", "gamma_best_ask"))
    if yes_bid is None:
        return {
            "no_best_bid": None,
            "no_best_ask": None,
            "no_ask_size_at_best": None,
            "no_book_source": "unavailable",
        }
    no_ask = clamp_probability(1.0 - yes_bid)
    no_bid = clamp_probability(1.0 - yes_ask) if yes_ask is not None else None
    # Buying NO at ``no_ask`` means hitting the YES bid, so the available size is
    # the YES bid depth (when the tape carries it).
    yes_bid_size = maybe_float(first_present(row, "bid_size_at_best", "clob_bid_size_at_best", "clob_best_bid_size"))
    yes_bid_depth_1pct = maybe_float(first_present(row, "bid_depth_1pct", "clob_bid_depth_1pct"))
    yes_book_age = maybe_float(first_present(row, "book_age_seconds", "clob_book_age_seconds"))
    return {
        "no_best_bid": compact_float(no_bid),
        "no_best_ask": compact_float(no_ask),
        "no_bid_size_at_best": None,
        "no_ask_size_at_best": compact_float(yes_bid_size),
        "no_ask_depth_1pct": compact_float(yes_bid_depth_1pct),
        "no_book_source": "synthetic_from_yes_bid",
        "no_book_captured_at_utc": "",
        "no_book_age_seconds": compact_float(yes_book_age),
    }


def no_edge(row):
    """Model edge on the NO side: ``fair_no - no_ask`` (positive = NO is cheap,
    i.e. the market over-prices the YES band). Returns None when unavailable."""
    fair_yes = clamp_probability((row or {}).get("fair_probability"))
    no_ask = maybe_float(no_book_fields(row).get("no_best_ask"))
    if fair_yes is None or no_ask is None:
        return None
    return (1.0 - fair_yes) - no_ask


def no_side_input_row(input_row, config=None):
    """Synthesize a NO-side candidate input row.

    Returns a copy of ``input_row`` re-pointed at the NO side: ``fair_probability``
    becomes ``1 - fair_yes``, the book columns become the NO book, and the traded
    token becomes the NO token. The band identity and current-high/source fields
    are preserved so every existing gate applies unchanged. Returns ``None`` when
    the NO token or a NO ask price is unavailable.
    """
    fair_yes = clamp_probability((input_row or {}).get("fair_probability"))
    token = no_token_id(input_row)
    book = no_book_fields(input_row)
    no_ask = maybe_float(book.get("no_best_ask"))
    if fair_yes is None or token is None or no_ask is None:
        return None
    max_age = float((config or {}).get("two_sided_real_no_book_max_age_seconds") or 120.0)
    min_depth = float((config or {}).get("two_sided_real_no_book_min_ask_size") or 0.0)
    age = maybe_float(book.get("no_book_age_seconds"))
    ask_size = maybe_float(book.get("no_ask_size_at_best")) or 0.0
    real_book = book.get("no_book_source") == "no_token_book"
    fresh = bool(real_book and age is not None and age <= max_age)
    depth_ok = ask_size > 0 and ask_size >= min_depth
    out = dict(input_row)
    out["taker_side"] = NO_SIDE
    out["yes_fair_probability"] = compact_float(fair_yes)
    out["fair_probability"] = compact_float(1.0 - fair_yes)
    out["calibrated_model_probability"] = compact_float(1.0 - fair_yes)
    out["calibrated_fair_probability"] = compact_float(1.0 - fair_yes)
    out["calibrated_fair"] = compact_float(1.0 - fair_yes)
    out["taker_edge_permission_hit_rate"] = compact_float(1.0 - fair_yes)
    out["clob_yes_token_id"] = input_row.get("clob_yes_token_id") or input_row.get("clob_token_id")
    out["clob_token_id"] = token
    out["clob_best_ask"] = book.get("no_best_ask")
    out["best_ask"] = book.get("no_best_ask")
    out["clob_best_bid"] = book.get("no_best_bid")
    out["best_bid"] = book.get("no_best_bid")
    out["ask_size_at_best"] = book.get("no_ask_size_at_best")
    out["clob_ask_size_at_best"] = book.get("no_ask_size_at_best")
    out["ask_depth_1pct"] = book.get("no_ask_depth_1pct")
    out["clob_ask_depth_1pct"] = book.get("no_ask_depth_1pct")
    out["clob_no_best_bid"] = book.get("no_best_bid")
    out["clob_no_best_ask"] = book.get("no_best_ask")
    out["clob_no_ask_size_at_best"] = book.get("no_ask_size_at_best")
    out["clob_no_bid_size_at_best"] = book.get("no_bid_size_at_best")
    out["clob_no_ask_depth_1pct"] = book.get("no_ask_depth_1pct")
    out["clob_no_book_captured_at_utc"] = book.get("no_book_captured_at_utc")
    out["clob_no_book_age_seconds"] = book.get("no_book_age_seconds")
    out["no_book_fresh"] = fresh
    out["real_no_book_depth_eligible"] = bool(real_book and fresh and depth_ok)
    # Recompute the mid from the NO book downstream rather than reuse the YES mid.
    out["market_mid"] = None
    out["market_yes"] = None
    out.update(book)
    return out


def no_buy_settlement_outcome(yes_outcome):
    """Invert a YES outcome for a NO buy. A NO buy wins when the band loses."""
    if yes_outcome is None:
        return None
    return 1.0 - float(yes_outcome)


def two_sided_enabled(config):
    value = (config or {}).get("two_sided_enabled")
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


__all__ = [
    "NO_SIDE",
    "YES_SIDE",
    "order_side",
    "no_token_id",
    "no_book_fields",
    "no_edge",
    "no_side_input_row",
    "no_buy_settlement_outcome",
    "two_sided_enabled",
]
