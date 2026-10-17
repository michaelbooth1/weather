"""Fictional fixtures for the fill model v3 and its reconciliation (item 330 build 1).

Nothing here is copied from a real journal or capture; every identifier, size and price is synthetic.

- ``journal_rows`` is the golden two-leg session for the hand-computed reconciliation. Its row shapes are the
  RE-1 writer's, but its sequencing is synthetic: the writer ends a session at its first fill, this one goes on.
- ``re1_writer_rows`` mirrors the row stream the RE-1 attended writer emits for one whole session
  (``weather.market.re1_attended.Session`` over ``mm_stage2_hold.HoldJournal``, branch
  ``codex/re1-wallet-200-20260923`` at ``2b9a0ca9e``): every event name it writes on that path in the writer's
  order, the events the reconciliation reads with the writer's exact fields, the others with abbreviated
  payloads. Redacted to synthetic values: no ids, addresses, tokens, hashes or signatures.
- ``write_journal`` adds the writer's envelope (``schema_version``, ``kind``, ``sequence``, ``previous_sha256``
  over the previous canonical line) and writes canonical lines exactly as ``HoldJournal.record`` does.
- ``engine_source`` builds a replay bundle whose first decision is forced to a known QUOTE.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
import hashlib
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


WRITER_SCHEMA = "mm_stage2_hold_v0.1"  # the writer's schema_registry value; tests only, never in src


def trade_event(order_id, size, price, outcome, token, condition_id):
    """``PairStream._normalize_event`` for a trade with one of our maker rows (synthetic values)."""
    return {"event_type": "trade", "official_event_type": "trade", "condition_id": condition_id,
            "order_id": order_id, "clob_token_id": token, "outcome": outcome, "side": "BUY", "fill_price": price,
            "fill_size": size, "official_trade_status": "CONFIRMED", "raw_event_sha256": "0" * 64}


def order_row(order_id, token, outcome, price, status, matched, condition_id):
    """``_plain_sdk_value(OpenOrder)`` after the writer's guard, synthetic values."""
    return {"id": order_id, "market": condition_id, "asset_id": token, "maker_address": "synthetic-maker",
            "side": "BUY", "price": price, "original_size": "20", "size_matched": matched, "outcome": outcome,
            "order_type": "GTD", "status": status, "created_at": 1577836800, "expiration": "1577840460",
            "associate_trades": []}


def terminal_fields(order_ids, reason, *, posts):
    return {"reason": reason, "failure_type": None, "cleanup_ok": True, "fill_seen": reason == "fill",
            "submits": posts, "requotes": 0, "evidence_complete": True, "reward_terms_changed": False,
            "scoring_seen": True, "order_ids": order_ids, "unknown_submit": False, "post_count": posts,
            "inventory_proven": True}


def opened(condition_id, start, mode="rehearse"):
    return {"event": "opened", "mode": mode, "profile_sha256": "0" * 64,
            "scope": {"condition_id": condition_id, "token_ids": [YES_TOKEN, NO_TOKEN],
                      "maker_address": "synthetic-maker", "end_at_utc": stamp(3600, start), "protocol": "fixture"}}


def submit_request(token, price, expiration=0):
    return {"event": "submit_request", "request": {"token_id": token, "side": "BUY", "size": "20", "price": price,
                                                   "post_only": True, "expiration": expiration}}


def journal_rows(condition_id="a-2020-01-01", start=DAY):
    """Two acknowledged legs and one refused submit on ``condition_id``.

    L1 YES .48 x20 acked at 58 s, cancelled at 600 s, one own fill of 5 at 160 s.
    L2 NO .47 x20 acked at 60 s, own fill of 20 at 305 s, terminal MATCHED at 360 s.
    A third submit is refused (ok false, no order id) and never becomes a leg.
    """
    rows = [
        (0, opened(condition_id, start)),
        (50, submit_request(YES_TOKEN, "0.48")),
        (58, {"event": "submit_response", "response": {"ok": True, "order_id": "ord-l1", "status": "live",
                                                       "trade_ids": []}}),
        (59, submit_request(NO_TOKEN, "0.47")),
        (60, {"event": "submit_response", "response": {"ok": True, "order_id": "ord-l2", "status": "live",
                                                       "trade_ids": []}}),
        (61, submit_request(NO_TOKEN, "0.46")),
        (62, {"event": "submit_response", "response": {"ok": False, "order_id": "", "status": "rejected"}}),
        (160, {"event": "fill", "rows": [], "user_event": trade_event("ord-l1", "5", "0.48", "Yes", YES_TOKEN,
                                                                      condition_id)}),
        (305, {"event": "fill", "rows": [], "user_event": trade_event("ord-l2", "20", "0.47", "No", NO_TOKEN,
                                                                      condition_id)}),
        (360, {"event": "terminal_order", "order": order_row("ord-l2", NO_TOKEN, "No", "0.47", "MATCHED", "20",
                                                            condition_id)}),
        (599, {"event": "cancel_request", "request": {"order_id": "ord-l1"}}),
        (600, {"event": "cancel_response", "response": {"canceled": ["ord-l1"], "not_canceled": {}}}),
        (900, {"event": "terminal", **terminal_fields(["ord-l1", "ord-l2"], "fill", posts=3)}),
    ]
    return [dict(row, recorded_at_utc=stamp(seconds, start)) for seconds, row in rows]


def re1_writer_rows(condition_id="c-synthetic", start=DAY):
    """One whole RE-1 attended session in the writer's event order, redacted to synthetic values.

    YES .48 posted (raw SDK reply shape), NO .47 posted (rehearsal reply shape); a requote cancels the YES leg
    and posts YES .47; a trade event fills 5 of the NO leg, which ends the session; cleanup cancels the two
    resting legs and reads every known order. Expected legs: ord-a (cancel at 300 s), ord-b (5 filled, cleanup
    cancel at 403 s), ord-c (cleanup cancel at 403 s); the fill and terminal order rows prove token outcomes.
    """
    book = {"condition_id": condition_id, "token_ids": [YES_TOKEN, NO_TOKEN], "observed_at_utc": stamp(0, start),
            "quote_inputs": {"yes_bids": [], "yes_asks": [], "no_bids": [], "no_asks": []}, "rules": {}}
    expiration = int((start + timedelta(seconds=3660)).timestamp())
    rows = []

    def add(at, event, **fields):
        rows.append((at, {"event": event, **fields}))

    def call(at, name, response, **request):  # Session.call
        add(at, name + "_request", request=request)
        add(at, name + "_response", response=response)

    def submit(at, token, price, reply):  # Session.submit
        call(at, "open_orders", [])
        call(at, "submit_snapshot", book)
        add(at, "submit_market_snapshot", snapshot=book)
        rows.append((at, submit_request(token, price, expiration)))
        add(at, "sdk_request", method="POST", path="/order")
        add(at, "signed_order_book", book={"token_id": token})
        add(at, "sdk_response", method="POST", path="/order", status=200, response=reply)
        add(at + 1, "submit_response", response=reply)
        call(at + 1, "scoring", {})

    raw_reply = {"errorMsg": "", "makingAmount": "9.6", "takingAmount": "20", "orderID": "ord-a",
                 "status": "live", "success": True, "tradeIDs": []}
    rows.append((0, opened(condition_id, start, mode="live")))
    add(0, "selection", selection_sha256="0" * 64, confirmation={"text": "synthetic"},
        fixed_end_at_utc=stamp(3600, start), attempt={"number": 1})
    call(1, "initial_open_orders", [])
    call(1, "initial_positions", [])
    call(1, "initial_balances", {"available_collateral": "50"})
    add(2, "read_unavailable", fact="opening_snapshot", exception_type="TimeoutError")
    call(3, "opening_snapshot", book)
    add(3, "opening_market_snapshot", snapshot=book)
    add(4, "wire_request", method="GET", sha256="0" * 64)
    call(4, "geoblock", {"blocked": False})
    add(5, "heartbeat_request")
    add(5, "heartbeat_v1_acknowledgment", response={"status": "ok"})
    add(5, "heartbeat_response", response={"status": "ok"})
    submit(10, YES_TOKEN, "0.48", raw_reply)
    submit(20, NO_TOKEN, "0.47", {"ok": True, "order_id": "ord-b", "status": "live", "trade_ids": []})
    add(60, "market_snapshot", snapshot=book)
    add(60, "minute", snapshot=book, prices=["0.48", "0.47"])
    call(61, "accrual", {"rows": []})
    add(62, "missing_sample", sample="scoring", exception_type="TimeoutError")
    add(70, "minute_missed", exception_type="TimeoutError")
    call(80, "order", order_row("ord-a", YES_TOKEN, "Yes", "0.48", "LIVE", "0", condition_id), order_id="ord-a")
    add(90, "heartbeat_unavailable", exception_type="TimeoutError")
    call(300, "cancel", {"canceled": ["ord-a"], "not_canceled": {}}, order_id="ord-a")
    call(301, "cancel_order_read", order_row("ord-a", YES_TOKEN, "Yes", "0.48", "CANCELED", "0", condition_id))
    submit(310, YES_TOKEN, "0.47", {"ok": True, "order_id": "ord-c", "status": "live", "trade_ids": []})
    fill = trade_event("ord-b", "5", "0.47", "No", NO_TOKEN, condition_id)
    add(400, "user_events", rows=[fill])
    read_b = order_row("ord-b", NO_TOKEN, "No", "0.47", "LIVE", "5", condition_id)
    call(401, "fill_order", read_b, order_id="ord-b")
    add(401, "fill_order_unavailable", order_id="ord-c", exception_type="TimeoutError")
    add(402, "fill", rows=[read_b], user_event=fill)
    for oid in ("ord-b", "ord-c"):
        add(403, "cleanup_cancel_request", order_id=oid)
        add(403, "cleanup_cancel_response", order_id=oid, response={"canceled": [oid], "not_canceled": {}})
    add(404, "cleanup_cancel_all_request")
    add(404, "cleanup_cancel_all_unavailable", exception_type="TimeoutError")
    add(405, "cleanup_cancel_all_response", response={"canceled": [], "not_canceled": {}})
    add(406, "cleanup_open_orders", rows=[])
    for oid, token, outcome, price, matched in (("ord-a", YES_TOKEN, "Yes", "0.48", "0"),
                                                ("ord-b", NO_TOKEN, "No", "0.47", "5"),
                                                ("ord-c", YES_TOKEN, "Yes", "0.47", "0")):
        add(407, "terminal_order", order=order_row(oid, token, outcome, price, "CANCELED", matched, condition_id))
    add(408, "terminal_positions", rows=[{"asset": NO_TOKEN, "size": "5"}])
    add(408, "terminal_trades", rows=[{"id": "trade-synthetic", "status": "MATCHED"}])
    call(409, "final_balances", {"available_collateral": "47.65"})
    call(409, "final_accrual", {"rows": []})
    add(410, "terminal", **terminal_fields(["ord-a", "ord-b", "ord-c"], "fill", posts=3))
    return [dict(row, recorded_at_utc=stamp(seconds, start)) for seconds, row in rows]


def canonical_line(row):
    """``mm_stage2_hold.canonical_bytes``: the writer's line bytes."""
    text = json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return text.encode("utf-8") + b"\n"


def write_journal(path, rows):
    """Write ``rows`` (event fields plus ``recorded_at_utc``) with the writer's envelope and hash chain."""
    path.parent.mkdir(parents=True, exist_ok=True)
    previous, lines = None, []
    for sequence, row in enumerate(rows):
        line = canonical_line({"schema_version": WRITER_SCHEMA, "kind": "journal", "sequence": sequence,
                               "previous_sha256": previous, **row})
        previous = hashlib.sha256(line).hexdigest()
        lines.append(line)
    path.write_bytes(b"".join(lines))
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
