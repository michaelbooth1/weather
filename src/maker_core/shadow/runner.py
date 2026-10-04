"""One shadow minute: public books and terms -> ``decide`` -> OrderGate -> local sink -> tape.

Nothing here can reach a venue. Public reads, the wallet book, fair value and
the clock are injected. Every would-quote leg asks ``OrderGate.authorize`` for
a permit and is "placed" only through ``GatedPlacement`` into ``ShadowSink``,
a local list. A PAUSE/HALT cancel-all intent withdraws every hypothetical leg.
The hypothetical portfolio holds no inventory: fills are simulated only by the
nightly scorer. Contract: docs/operations/maker-shadow-runner.md.
"""
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Callable, Mapping, Protocol

from maker_core.contracts import MarketDescriptor, OutcomeView, Unavailable
from maker_core.evidence.journal import digest, plain
from maker_core.quoting.policy import Book, DecisionInputs, Portfolio, RewardTerms, decide
from maker_core.runtime.guard import ALLOW, GatedPlacement, GuardRefused, OrderGate
from maker_core.shadow.tape import decision_projection, inputs_projection

D = Decimal
MAX_LEVELS = 25


@dataclass(frozen=True)
class ShadowMarket:
    descriptor: MarketDescriptor
    horizon_days: int  # Plugin-owned local-date horizon.


@dataclass(frozen=True)
class ShadowOrder:
    """What the runner would post. A local record; it carries no signature and no venue identity."""
    condition_id: str
    outcome: str
    asset_id: str
    price: Decimal
    size: Decimal


class PublicReads(Protocol):
    def book(self, asset_id) -> Mapping: ...
    def reward_terms(self, condition_id) -> Mapping | None: ...


class ShadowSink:
    """The ``send`` behind ``GatedPlacement``: appends a would-quote leg to a list. No network."""

    def __init__(self):
        self.accepted = []

    def __call__(self, order):
        if not isinstance(order, ShadowOrder):
            raise TypeError("shadow_order_required")
        self.accepted.append(order)
        return "local_shadow_ack"


class ShadowCancelPort:
    """``CancelAllPort`` for the shadow: records the intent and withdraws hypothetical legs."""

    def __init__(self):
        self.intents, self.listeners = [], []

    def request_cancel_all(self, intent):
        self.intents.append(intent)
        for listener in self.listeners:
            listener(intent)


def _levels(rows, *, descending):
    levels = []
    for row in rows or ():
        price, size = D(str(row["price"])), D(str(row["size"]))
        if not price.is_finite() or not size.is_finite() or not 0 < price < 1 or size <= 0:
            raise ValueError("invalid_book_level")
        levels.append((price, size))
    return tuple(sorted(levels, reverse=descending)[:MAX_LEVELS])


def book_from_public(yes, no, condition_id, as_of_utc):
    """Both-token CLOB books -> policy ``Book``; ``as_of`` is the local receipt time of the later read."""
    for book in (yes, no):
        if str(book.get("market", "")).lower() != condition_id:
            raise ValueError("book_condition_mismatch")
    return Book(as_of_utc, _levels(yes.get("bids"), descending=True), _levels(yes.get("asks"), descending=False),
                _levels(no.get("bids"), descending=True), _levels(no.get("asks"), descending=False))


def terms_from_public(record, as_of_utc):
    """Current CLOB reward record -> ``RewardTerms``; None (a refusal reason) when absent or inactive."""
    if record is None:
        return None, "no_reward_record"
    today = as_of_utc.date().isoformat()
    try:
        rate = sum((D(str(row["rate_per_day"])) for row in record.get("rewards_config") or ()
                    if str(row["start_date"])[:10] <= today <= str(row["end_date"])[:10]), D(0))
        return RewardTerms(as_of_utc, D(str(record["rewards_min_size"])), D(str(record["rewards_max_spread"])),
                           rate), None
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return None, "reward_terms_inactive_or_invalid"


def _reserve(legs):
    return sum((leg.price * leg.size for leg in legs), D(0))


class ShadowRunner:
    def __init__(self, *, reads: PublicReads, gate: OrderGate, cancel_port: ShadowCancelPort,
                 wallet_book: Callable[[], dict], fair_value: Callable, clock: Callable[[], datetime],
                 caps: Mapping[str, Decimal], hazard_per_minute: float, adverse_markout: float,
                 profile, placement: GatedPlacement | None = None):
        if not isinstance(gate, OrderGate) or gate.cancel_port is not cancel_port:
            raise TypeError("order_gate_with_shadow_cancel_port_required")
        self.reads, self.gate, self.wallet_book = reads, gate, wallet_book
        self.fair_value, self.clock, self.profile = fair_value, clock, profile
        self.caps = {k: D(str(caps[k])) for k in ("cash", "band_cap", "order_cap", "wallet_cap", "event_cap")}
        self.hazard, self.adverse = hazard_per_minute, adverse_markout
        self.sink = ShadowSink()
        self.placement = placement or GatedPlacement(gate, self.sink)
        if not isinstance(self.placement, GatedPlacement):
            raise TypeError("gated_placement_required")
        self.resting, self.placed_at, self.previous_view = {}, {}, {}
        self.minute_intents, self.events = [], {}
        cancel_port.listeners.append(self._withdraw_all)

    def _withdraw_all(self, intent):
        self.resting.clear()
        self.minute_intents.append({"trigger": intent.trigger, "reasons": list(intent.reasons),
                                    "decided_at_utc": intent.decided_at_utc, "scope": intent.scope})

    def _portfolio(self, market):
        others = {cid: legs for cid, legs in self.resting.items() if cid != market.condition_id}
        committed = sum((_reserve(legs) for legs in others.values()), D(0))
        same_event = sum((_reserve(legs) for cid, legs in others.items()
                          if self.events.get(cid) == market.event_id), D(0))
        c = self.caps
        return Portfolio(c["cash"], committed, c["band_cap"], c["order_cap"], committed, c["wallet_cap"],
                         same_event, c["event_cap"], active_other_bands=len(others))

    def _wallet(self):
        try:
            book = self.wallet_book()
            return book if isinstance(book, dict) else {"unreadable": "wallet_book_not_object"}
        except Exception as error:  # Any unreadable book is a guard HALT, never a crash or an ALLOW.
            return {"unreadable": "wallet_book_unreadable:" + type(error).__name__}

    def _place(self, market, decision, wallet, now):
        rows, placed = [], []
        for leg in decision.legs:
            order = ShadowOrder(market.condition_id, leg.outcome, market.outcome_tokens[leg.outcome],
                                leg.price, leg.size)
            try:
                permit = self.gate.authorize(wallet)
                self.placement.place(order, permit)
            except GuardRefused as refused:
                rows.append({"outcome": leg.outcome, "action": refused.decision.action,
                             "reasons": list(refused.decision.reasons), "placed": False})
                break
            except PermissionError as refused:
                rows.append({"outcome": leg.outcome, "action": "REFUSED_AT_REDEEM", "reasons": [str(refused)],
                             "placed": False})
                break
            rows.append({"outcome": leg.outcome, "action": ALLOW, "reasons": [], "placed": True})
            placed.append(leg)
        if len(placed) == len(decision.legs):
            self.resting[market.condition_id] = tuple(placed)
            self.placed_at[market.condition_id] = now
        else:
            # A partly gated band is never left one-sided: withdraw what was placed.
            self.resting.pop(market.condition_id, None)
        return rows

    def step(self, minute_utc, markets):
        """Evaluate every market once; return the ``minute`` tape payload."""
        self.minute_intents = []
        self.events = {m.descriptor.condition_id: m.descriptor.event_id for m in markets}
        wallet = self._wallet()
        check = self.gate.check(wallet)
        record = {"guard": {"action": check.action, "reasons": list(check.reasons),
                            "book_sha256": check.book_sha256},
                  "wallet_book_sha256": digest(wallet), "conditions": []}
        for market in sorted(markets, key=lambda m: m.descriptor.condition_id):
            record["conditions"].append(self._condition(market, wallet))
        record["cancel_all"] = list(self.minute_intents)
        record["resting_after"] = {cid: plain(legs) for cid, legs in sorted(self.resting.items())}
        return record

    def _condition(self, market, wallet):
        d = market.descriptor
        row = {"condition_id": d.condition_id, "event_id": d.event_id, "horizon_days": market.horizon_days,
               "outcomes": dict(d.outcome_tokens)}
        try:
            yes, no = (self.reads.book(d.outcome_tokens[o]) for o in ("YES", "NO"))
            reward = self.reads.reward_terms(d.condition_id)
            received = self.clock()
            book = book_from_public(yes, no, d.condition_id, received)
            tick, minimum = D(str(yes.get("tick_size", d.tick))), D(str(yes.get("min_order_size", d.min_order_size)))
            descriptor = replace(d, tick=tick, min_order_size=minimum)
        except Exception as error:  # Unreadable public input: recorded, never quoted on.
            self.resting.pop(d.condition_id, None)
            row["unevaluated"] = "public_input_unavailable:" + type(error).__name__
            return row
        terms, terms_reason = terms_from_public(reward, received)
        now = self.clock()
        view = self.fair_value(descriptor, now)
        if not isinstance(view, (OutcomeView, Unavailable)):
            raise TypeError("fair_value_provider_contract")
        inputs = DecisionInputs(
            market=descriptor, now=now, book=book, terms=terms, fair_value=view,
            portfolio=self._portfolio(descriptor), horizon_days=market.horizon_days, profile=self.profile,
            hazard_per_minute=self.hazard, adverse_markout=self.adverse,
            existing=self.resting.get(d.condition_id, ()), last_requote_at=self.placed_at.get(d.condition_id),
            previous_fair_value=self.previous_view.get(d.condition_id))
        decision = decide(inputs)
        row.update(inputs=inputs_projection(inputs), decision=decision_projection(decision),
                   venue={"yes_timestamp": yes.get("timestamp"), "no_timestamp": no.get("timestamp"),
                          "terms_reason": terms_reason})
        if isinstance(view, OutcomeView):
            self.previous_view[d.condition_id] = view.p_yes
        if decision.action == "QUOTE":
            self.resting.pop(d.condition_id, None)
            row["gate"] = self._place(descriptor, decision, wallet, now)
        elif decision.action != "HOLD":
            self.resting.pop(d.condition_id, None)
        return row


__all__ = ["ShadowCancelPort", "ShadowMarket", "ShadowOrder", "ShadowRunner", "ShadowSink",
           "book_from_public", "terms_from_public"]
