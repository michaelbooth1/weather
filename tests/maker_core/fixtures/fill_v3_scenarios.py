"""Fictional fixtures for the fill model v3 and its reconciliation (item 330 build 1).

Nothing here is copied from a real journal or capture. ``journal_rows`` builds rows shaped like an RE-1 session
journal (event names and the fields the reconciliation reads; no addresses, signatures, hashes or venue IDs).
``engine_source`` builds a replay bundle whose first decision is forced to a known QUOTE.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
import json

from maker_core.quoting.policy import Book, QuoteDecision, QuoteLeg
from maker_core.replay.v2 import kernel as kernel_module
from maker_core.replay.v2.lockstep import bundle_source
from .replay_scenario import Scenario

LEGS = (QuoteLeg("YES", D(".48"), D(20)), QuoteLeg("NO", D(".48"), D(20)))
# Displayed size at .48: 30 on yes_bids (the YES leg's queue), 10 on no_bids (the NO leg's queue).
SIDES = dict(yb=((D(".49"), D(75)), (D(".48"), D(30))), ya=((D(".51"), D(75)),),
             nb=((D(".49"), D(75)), (D(".48"), D(10))), na=((D(".51"), D(75)),))


def public(s, seconds, sides=SIDES, market="a"):
    s.add(market, "coverage", seconds, dict(trade_stream_ok=True, valid_until_utc=s.at(seconds + 60).isoformat()))
    s.add(market, "book", seconds, Book(s.at(seconds), sides["yb"], sides["ya"], sides["nb"], sides["na"]))


def engine_source(tmp_path, trades, *, day=date(2020, 1, 1), name="bundle"):
    """Books every 30 s for three minutes; ``trades`` are (seconds, price, size, outcome) prints on market a."""
    s = Scenario(day=day, markets=("a",), minutes=3)
    s.view("a", 0, p=.5, grade="shadow")
    for seconds in range(0, 180, 30):
        public(s, seconds)
    for n, (seconds, price, size, outcome) in enumerate(trades):
        s.trade("a", seconds, price, size, outcome, trade_id=f"t{n}")
    return bundle_source(s.bundle(tmp_path / name))


class Forced:
    """decide(): the first call quotes ``LEGS``; later calls hold resting legs or do not quote."""

    def __init__(self):
        self.calls = 0

    def __call__(self, value):
        self.calls += 1
        if self.calls == 1:
            return QuoteDecision("QUOTE", LEGS, ("FORCED_FIXTURE_QUOTE",), "0" * 64, value.profile.name)
        if value.existing:
            return QuoteDecision("HOLD", value.existing, ("FORCED_FIXTURE_HOLD",), "0" * 64, value.profile.name)
        return QuoteDecision("NO_QUOTE", (), ("FORCED_FIXTURE_NO_QUOTE",), "0" * 64, value.profile.name)


def force(monkeypatch):
    forced = Forced()
    monkeypatch.setattr(kernel_module, "decide", forced)
    return forced


# -- RE-1-shaped session journal --------------------------------------------------------------------------
DAY = datetime(2020, 1, 1, tzinfo=timezone.utc)
YES_TOKEN, NO_TOKEN = "tok-yes", "tok-no"


def stamp(seconds, start=DAY):
    return (start + timedelta(seconds=seconds)).isoformat()


def journal_rows(condition_id="a-2020-01-01", start=DAY):
    """Two acknowledged legs and one refused submit on ``condition_id``.

    L1 YES .48 x20 acked at 58 s, cancelled at 600 s, one own fill of 5 at 160 s.
    L2 NO .47 x20 acked at 60 s, own fill of 20 at 305 s, terminal MATCHED at 360 s.
    A third submit is refused (ok false) and never becomes a leg.
    """
    rows = [
        (0, {"event": "opened", "scope": {"condition_id": condition_id, "token_ids": [YES_TOKEN, NO_TOKEN],
                                          "end_at_utc": stamp(3600, start), "protocol": "fixture"}}),
        (50, {"event": "submit_request", "request": {"expiration": 0, "post_only": True, "price": "0.48",
                                                     "side": "BUY", "size": "20", "token_id": YES_TOKEN}}),
        (58, {"event": "submit_response", "response": {"ok": True, "order_id": "ord-l1", "status": "live"}}),
        (59, {"event": "submit_request", "request": {"expiration": 0, "post_only": True, "price": "0.47",
                                                     "side": "BUY", "size": "20", "token_id": NO_TOKEN}}),
        (60, {"event": "submit_response", "response": {"ok": True, "order_id": "ord-l2", "status": "live"}}),
        (61, {"event": "submit_request", "request": {"expiration": 0, "post_only": True, "price": "0.46",
                                                     "side": "BUY", "size": "20", "token_id": NO_TOKEN}}),
        (62, {"event": "submit_response", "response": {"ok": False, "order_id": "", "status": "rejected"}}),
        (160, {"event": "fill", "rows": [], "user_event": {"order_id": "ord-l1", "fill_size": "5",
                                                           "fill_price": "0.48", "outcome": "Yes",
                                                           "clob_token_id": YES_TOKEN, "side": "BUY"}}),
        (305, {"event": "fill", "rows": [], "user_event": {"order_id": "ord-l2", "fill_size": "20",
                                                           "fill_price": "0.47", "outcome": "No",
                                                           "clob_token_id": NO_TOKEN, "side": "BUY"}}),
        (360, {"event": "terminal_order", "order": {"id": "ord-l2", "status": "MATCHED", "size_matched": "20",
                                                    "outcome": "No", "token_id": NO_TOKEN, "price": "0.47",
                                                    "side": "BUY"}}),
        (599, {"event": "cancel_request", "request": {"order_id": "ord-l1"}}),
        (600, {"event": "cancel_response", "response": {"canceled": ["ord-l1"], "not_canceled": {}}}),
        (900, {"event": "terminal", "order_ids": ["ord-l1", "ord-l2"], "fill_seen": True}),
    ]
    out = []
    for n, (seconds, row) in enumerate(rows):
        out.append(dict(row, kind="journal", sequence=n, schema_version="fixture",
                        recorded_at_utc=stamp(seconds, start)))
    out.sort(key=lambda r: (r["recorded_at_utc"], r["sequence"]))
    return out


def write_journal(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(json.dumps(r, sort_keys=True).encode() + b"\n" for r in rows))
    return path


def reconcile_bundle(tmp_path, *, day=date(2020, 1, 1), name="bundle88a"):
    """The 88a side of the golden reconciliation for ``journal_rows`` (market a, condition a-<day>)."""
    s = Scenario(day=day, markets=("a",), minutes=20)
    yb = ((D(".48"), D(30)),)
    nb = ((D(".47"), D(10)),)
    s.add("a", "book", 0, Book(s.at(0), yb, ((D(".52"), D(50)),), nb, ((D(".53"), D(50)),)))
    # After the acknowledgement (ignored for q_ahead).
    s.add("a", "book", 120, Book(s.at(120), ((D(".48"), D(999)),), ((D(".52"), D(50)),), ((D(".47"), D(999)),),
                                 ((D(".53"), D(50)),)))
    for n, (seconds, price, size, outcome) in enumerate([
            (30, ".48", "50", "YES"),   # before the acknowledgement: no leg sees it
            (90, ".48", "25", "YES"),   # L1 at price: queue 30 -> 5
            (120, ".47", "10", "YES"),  # L1 through: queue 5 -> 0, v3 fill 5
            (150, ".48", "8", "YES"),   # L1 at price: v3 fill 8 (13 in all)
            (200, ".47", "6", "NO"),    # L2 at price: queue 10 -> 4
            (300, ".46", "12", "NO"),   # L2 through: queue 4 -> 0, v3 fill 8
            (310, ".55", "3", "YES")]):  # L2 through on the YES axis, after L2's full fill: unseen
        s.trade("a", seconds, price, size, outcome, trade_id=f"p{n}")
    s.bundle(tmp_path / name)
    return tmp_path / name
