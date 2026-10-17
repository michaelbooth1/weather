"""The informed-v1 frontier runner (item 330 build 3). Offline, read-only, embargoed and gated by a prereg.

``run`` replays sealed day sources (``lockstep.DaySource``) once. It evaluates every grid point and every
baseline side by side on the same instants. It never writes, never touches a venue and grants no
authority.

Modes:

- ``descriptive``: needs no registration. Its result is labelled DESCRIPTIVE. It is bounds-only by
  construction, and its numbers are not a P&L sign test (established findings §10r).
- ``scored``: refused unless it covers the whole grid and every baseline, and ``prereg.verify`` accepts
  the registration document for this run's decay digest and fill-model binding (``seams.binding``; an
  unregistered or unversioned fill model is refused). ``now`` (scored only) is passed to every embargo check,
  so the scored panel opens only by the caller's clock (``embargo.SCORED_OPENS_AT``). Both modes pass the date
  embargo on the day, the condition windows, every instant, every trade time, every market close and
  settle time, and every settlement.

Per band and strategy, decisions are made at each book arrival. A quote is held until the next book for
that band, and for at most ``HOLD_SECONDS``.

A **declared** day plan (``plan.declared``: windows from ``maker_core.replay.v2.intervals.sources``, the §4
rule and owner exclusions) is honoured (build 4): a band quotes only at a book inside one of its windows, and
a quote earns and fills only until that window's end. A band with no window never quotes. An undeclared
synthetic plan keeps the envelope behaviour of build 3.

- **Rewards** accrue at rate/86400 per second times the share. The share is computed under each
  competitor-response bound (``share_decay.BOUNDS``), with age measured from the start of the band's
  continuous quoting spell.
- **Fills** come from the injected ``FillModel``. The first fill ends quoting on that band-day for every
  strategy.
- **Adverse cost** is the filled shares times the markout from the injected ``FillCostProvider``, with
  0.0043 as the floor. Every decision where the provider gave no markout is counted in ``cost_unavailable``,
  and the provider type is recorded. A real provider without a ``context_builder`` is refused. Realised
  settlement P&L is reported separately.
- **Inventory** is either held to settlement or offered at entry plus twice the width. The offer is
  matched as the complementary BUY, since a NO buy at 1-q is a YES offer at q.

These are simplifications that the preregistration names:

- each band has its own 60/100 cash caps, with no cross-band capital;
- baselines are re-proposed through the frozen ``policy.decide`` at every book with no existing legs, so
  RE-1's hold/requote observer is not modelled;
- coverage records are not used.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_CEILING

from maker_core.contracts import OutcomeView, SettlementFact, Unavailable
from maker_core.evidence.journal import digest
from maker_core.frontier import embargo, prereg
from maker_core.frontier.adapters import RecordingFillCost
from maker_core.frontier.grid import BASELINES, GRID, GRID_HASH, GridPoint
from maker_core.frontier.seams import (
    ConstantFillCost, PricePathFillModel, binding, fill_cost_terms, is_bindable, no_context,
)
from maker_core.frontier.share_decay import BOUNDS, DecayModel
from maker_core.quoting.policy import (
    Book, DecisionInputs, Portfolio, QuoteLeg, RewardTerms, _event_active, blind_re1, decide, informed_v0,
)
from maker_core.quoting.prices import QuoteRefused, outward, qualified_mid, touch_buffer
from maker_core.quoting.rewards import order_score, q_min, share_of, side_score
from maker_core.replay.payloads import Descriptor, Trade
from maker_core.replay.v2.lockstep import items

D = Decimal
MODES = ("descriptive", "scored")
RUN_FORMAT = "maker-core.frontier-run.0"
HOLD_SECONDS = 120
LEG_CASH_CAP, BAND_CASH_CAP = D(60), D(100)
PROFILES = {"blind_re1": blind_re1, "informed-v0": informed_v0}


class FrontierRefused(ValueError):
    """The run's inputs are outside its contract."""


@dataclass
class Band:
    descriptor: Descriptor | None = None
    book: Book | None = None
    terms: RewardTerms | None = None
    view: object = None
    events: tuple = ()
    settlement: float | None = None


_INSTANT = timedelta(microseconds=1)


@dataclass
class Quote:
    legs: tuple | None = None
    fill_state: object = None
    spell_start: datetime | None = None
    accrued_to: datetime | None = None
    book_at: datetime | None = None
    own: float = 0.0
    competing: float = 0.0
    rate: float = 0.0
    markout: float = 0.0043
    width: Decimal | None = None
    window_end: datetime | None = None  # a declared plan's current window end; None when undeclared
    ended: bool = False
    positions: list = field(default_factory=list)  # [outcome, price, held size]
    exits: list = field(default_factory=list)      # [position index, leg, fill state]


def _totals():
    return {"reward": {b: 0.0 for b in BOUNDS}, "quoted_seconds": 0.0, "quotes": 0, "fills": 0,
            "filled_shares": D(0), "adverse_cost": 0.0, "exit_pnl": D(0), "settlement_pnl": D(0),
            "unsettled_shares": D(0), "vetoes": 0, "cost_unavailable": 0}


def _external_depth(levels, mid, terms):
    return sum((size for price, size in levels if abs(price - mid) * 100 < terms.max_spread_cents), D(0))


def economics(legs, mid, book, terms):
    """(own Q, competing Q) for symmetric BUY legs against the replayed (own-free) book."""
    scores = {leg.outcome: order_score(float(leg.size),
                                       float(((mid if leg.outcome == "YES" else 1 - mid) - leg.price) * 100),
                                       float(terms.max_spread_cents), float(terms.min_size)) for leg in legs}
    own = q_min(scores.get("YES", 0.0), scores.get("NO", 0.0), float(mid))
    sides = [side_score([(float(p), float(s)) for p, s in rows], float(mid), float(terms.max_spread_cents),
                        float(terms.min_size))[0] for rows in (book.yes_bids, book.yes_asks)]
    return own, sum(sides) / 2


def propose(point: GridPoint, band: Band, at: datetime):
    """informed-v1 legs and (own, competing) for one grid point, or None. Symmetric about the mid."""
    market, book, terms = (band.descriptor.market if band.descriptor else None), band.book, band.terms
    if market is None or book is None or terms is None or not book.post_only_available:
        return None
    if not 0 <= (at - book.as_of_utc).total_seconds() <= 10 or not 0 <= (at - terms.as_of_utc).total_seconds() <= 3600:
        return None
    if market.close_at_utc - at <= timedelta(hours=3) or band.descriptor.horizon_days not in (1, 2):
        return None
    active = [e for e in band.events if market.condition_id in e.affects and _event_active(e, at)]
    if any((e.decided or {}).get(market.condition_id, 0) >= .5 or e.action_hint == "pull" for e in active):
        return None
    try:
        mid = qualified_mid(book.yes_bids, book.yes_asks, terms.min_size)
    except QuoteRefused:
        return None
    if not D(".2") <= mid <= D(".8"):
        return None
    width, tick, size = point.width_cents, market.tick, D(point.size)
    if width > terms.max_spread_cents - tick * 100 or size < max(terms.min_size, market.min_order_size):
        return None
    legs = (QuoteLeg("YES", outward(mid - width / 100, tick), size),
            QuoteLeg("NO", outward(1 - mid - width / 100, tick), size))
    for leg, centre, asks in ((legs[0], mid, book.yes_asks), (legs[1], 1 - mid, book.no_asks)):
        if leg.price <= 0 or (centre - leg.price) * 100 >= terms.max_spread_cents:
            return None
        if not touch_buffer(leg.price, asks, tick) or leg.price * size > LEG_CASH_CAP:
            return None
    if sum(leg.price * size for leg in legs) > BAND_CASH_CAP:
        return None
    floor = max(D(75), size)
    if min(_external_depth(book.yes_bids, mid, terms), _external_depth(book.yes_asks, mid, terms)) < floor:
        return None
    own, competing = economics(legs, mid, book, terms)
    if point.band_rule in ("depth_share", "depth_share_fv") and not .15 <= share_of(own, competing) <= .70:
        return None
    if point.band_rule == "depth_share_fv":
        view = band.view
        if (not isinstance(view, OutcomeView) or view.condition_id != market.condition_id
                or not view.as_of_utc <= at < view.valid_until_utc or abs(view.p_yes - float(mid)) > view.stdev):
            return None
    return legs, own, competing


def baseline(name: str, band: Band, at: datetime, *, hazard, markout, others_live: int):
    if name == "no-quote" or band.descriptor is None or band.book is None:
        return None
    view = band.view if band.view is not None else Unavailable("no_captured_view", at)
    portfolio = Portfolio(D(100), D(0), D(100), D(60), D(0), D(100), D(0), D(100), active_other_bands=others_live)
    inputs = DecisionInputs(band.descriptor.market, at, band.book, band.terms, view, portfolio,
                            band.descriptor.horizon_days, band.events, PROFILES[name],
                            hazard_per_minute=hazard, adverse_markout=markout)
    decision = decide(inputs)
    if decision.action != "QUOTE" or decision.centre is None:
        return None
    own, competing = economics(decision.legs, decision.centre, band.book, band.terms)
    return decision.legs, own, competing


def _exit_leg(position, width, tick):
    outcome, price, size = position
    offer = ((price + 2 * width / 100) / tick).to_integral_value(rounding=ROUND_CEILING) * tick
    if offer >= 1:
        return None
    return QuoteLeg("NO" if outcome == "YES" else "YES", 1 - offer, size)


def run(sources, *, decay: DecayModel, mode: str = "descriptive", registration: bytes | None = None,
        fill_model=None, cost_provider=None, context_builder=no_context, hazard_per_minute: float | None = None,
        points=GRID, baselines=BASELINES, now=None, decision_rule_digest: str | None = None) -> dict:
    """Replay ``sources`` once for every strategy (module doc).

    A scored run also needs a fill-cost provider that is exactly ``adapters.RecordingFillCost`` (the build 2
    table), whose digest is its wrapped table's. A duck type, the constant stand-in or no provider is
    refused, and the digest must equal the registration's ``Toxicity table:`` line."""
    if mode not in MODES:
        raise FrontierRefused("unknown_mode")
    if not isinstance(decay, DecayModel):
        raise FrontierRefused("decay_model_required")
    fill_model = fill_model or PricePathFillModel()
    fill_binding = binding(fill_model)
    clock = now if mode == "scored" else None

    def check(*values):
        if clock is None:
            embargo.check(mode, *values)
        else:
            embargo.check(mode, *values, now=clock)

    cost_provider = cost_provider or ConstantFillCost()
    if not isinstance(cost_provider, ConstantFillCost) and context_builder is no_context:
        raise FrontierRefused("context_builder_required")
    unknown = [b for b in baselines if b not in BASELINES]
    if unknown:
        raise FrontierRefused("unknown_baseline")
    registration_sha = None
    if mode == "scored":
        if tuple(sorted(points)) != GRID:
            raise FrontierRefused("scored_requires_full_grid")
        if tuple(baselines) != BASELINES:
            raise FrontierRefused("scored_requires_all_baselines")
        if not is_bindable(fill_binding):
            raise FrontierRefused("scored_requires_registered_fill_model")
        # the class, not a duck type: only the recording adapter checks the table version and digest on entry
        if type(cost_provider) is not RecordingFillCost:
            raise FrontierRefused("scored_requires_fill_cost_table")
        table_digest = cost_provider.table_digest
        if not isinstance(table_digest, str) or table_digest != cost_provider.provider.digest:
            raise FrontierRefused("scored_fill_cost_table_digest_inconsistent")
        registration_sha = prereg.verify(registration, decay_digest=decay.digest(), fill_model_binding=fill_binding,
                                         decision_rule_digest=decision_rule_digest,
                                         toxicity_table_digest=table_digest)
    strategies = {name: name for name in baselines}
    strategies.update({p.label: p for p in sorted(points)})
    totals = {label: _totals() for label in strategies}
    days = []
    for source in sources:
        plan = source.plan
        # windows are half-open [from, until): the last instant read is just before ``active_until`` (a
        # 09-29 envelope ends at 09-30T00:00Z without reading 09-30)
        check(plan.day, *(t for c in plan.conditions for t in (c.active_from, c.active_until - _INSTANT)))
        days.append(plan.day.isoformat())
        bands, quotes = {}, {}
        declared = bool(getattr(plan, "declared", False))

        def window_end(cid, at, plan=plan):
            """The end of the declared window holding ``at`` (None outside every window)."""
            for start, end in plan.windows.get(cid, ()):
                if start <= at < end:
                    return end
            return None

        def accrue(label, cid, until):
            q = quotes[label, cid]
            if q.legs is None or q.accrued_to is None:
                return
            end = min(until, q.book_at + timedelta(seconds=HOLD_SECONDS))
            if q.window_end is not None:
                end = min(end, q.window_end)
            seconds = (end - q.accrued_to).total_seconds()
            if seconds <= 0:
                return
            age = ((q.accrued_to - q.spell_start).total_seconds() + seconds / 2) / 60
            for bound in BOUNDS:
                totals[label]["reward"][bound] += q.rate / 86400 * seconds * decay.share(bound, q.own, q.competing, age)
            totals[label]["quoted_seconds"] += seconds
            q.accrued_to = end

        def fill(label, cid, trade, band, at):
            q = quotes[label, cid]
            t = totals[label]
            for i, (index, leg, state) in enumerate(list(q.exits)):
                state, hits = fill_model.on_trade(state, trade)
                q.exits[i] = [index, leg, state]
                for _, size in hits:
                    position = q.positions[index]
                    size = min(size, position[2])
                    position[2] -= size
                    t["exit_pnl"] += size * (1 - position[1] - leg.price)
            if q.legs is None or (q.book_at is not None and at > q.book_at + timedelta(seconds=HOLD_SECONDS)):
                return
            if q.window_end is not None and at >= q.window_end:
                return  # outside its declared window the quote is gone  # a quote is not fillable after its hold lapses, as it earns no reward then either
            q.fill_state, hits = fill_model.on_trade(q.fill_state, trade)
            if not hits:
                return
            accrue(label, cid, at)
            for leg, size in hits:
                t["fills"] += 1
                t["filled_shares"] += size
                t["adverse_cost"] += float(size) * q.markout
                q.positions.append([leg.outcome, leg.price, size])
                point = strategies[label]
                if isinstance(point, GridPoint) and point.inventory == "resting_sell" and band.book is not None:
                    exit_leg = _exit_leg(q.positions[-1], point.width_cents, band.descriptor.market.tick)
                    if exit_leg is not None:
                        q.exits.append([len(q.positions) - 1, exit_leg, fill_model.place((exit_leg,), band.book)])
            q.legs, q.ended = None, True

        def decide_band(label, cid, band, at):
            q = quotes[label, cid]
            if q.ended:
                return
            accrue(label, cid, at)
            limit = window_end(cid, at) if declared else None
            if declared and limit is None:  # outside every declared window: no quote, no cost query
                q.legs, q.spell_start, q.accrued_to = None, None, None
                return
            strategy = strategies[label]
            live = sum(1 for (l, c), other in quotes.items() if l == label and c != cid and other.legs)
            context = context_builder(condition_id=cid, at=at, band=band, strategy=label)
            estimate = cost_provider.estimate(context)
            if getattr(estimate, "adverse_markout_upper", None) is None:
                totals[label]["cost_unavailable"] += 1
            markout, veto = fill_cost_terms(estimate)
            if veto:
                totals[label]["vetoes"] += 1
                proposal = None
            elif isinstance(strategy, GridPoint):
                proposal = propose(strategy, band, at)
            else:
                proposal = baseline(strategy, band, at, hazard=hazard_per_minute, markout=markout,
                                    others_live=live)
            if proposal is None:
                q.legs, q.spell_start, q.accrued_to = None, None, None
                return
            legs, own, competing = proposal
            if legs != q.legs:
                q.fill_state = fill_model.place(legs, band.book)
                totals[label]["quotes"] += 1
            if q.legs is None:
                q.spell_start = at
            q.legs, q.own, q.competing, q.markout = legs, own, competing, markout
            q.rate, q.accrued_to, q.book_at = float(band.terms.rate_per_day), at, at
            q.window_end = limit

        last = None
        for at, batch in items(source):
            check(at)
            last = at
            booked = []
            for item in batch:
                if item.error is not None:
                    continue
                cid, value = item.condition_id, item.value
                band = bands.setdefault(cid, Band())
                if item.kind == "descriptor":
                    market = value.market
                    check(market.close_at_utc, *([market.settle_at_utc] if market.settle_at_utc else []))
                    band.descriptor = value
                    for label in strategies:
                        quotes.setdefault((label, cid), Quote())
                elif band.descriptor is None:
                    continue
                elif item.kind == "book":
                    band.book = value
                    booked.append(cid)
                elif item.kind == "terms":
                    band.terms = value
                elif item.kind == "outcome_view":
                    band.view = value
                elif item.kind == "info_event":
                    band.events = value
                elif item.kind == "settlement" and isinstance(value, SettlementFact):
                    check(value.as_of_utc)
                    band.settlement = value.p_yes
                elif item.kind == "trade" and isinstance(value, Trade):
                    check(value.traded_at)
                    for label in strategies:
                        fill(label, cid, value, band, at)
            for cid in booked:
                for label in strategies:
                    decide_band(label, cid, bands[cid], at)
        if last is not None:
            for label, cid in list(quotes):
                accrue(label, cid, last + timedelta(seconds=HOLD_SECONDS))
        for (label, cid), q in quotes.items():
            settled = bands[cid].settlement
            for outcome, price, size in q.positions:
                if size <= 0:
                    continue
                if settled is None:
                    totals[label]["unsettled_shares"] += size
                    continue
                value = D(str(settled)) if outcome == "YES" else 1 - D(str(settled))
                totals[label]["settlement_pnl"] += size * (value - price)
    for t in totals.values():
        t["net_modelled"] = {b: t["reward"][b] - t["adverse_cost"] for b in BOUNDS}
    result = {"format": RUN_FORMAT, "label": "SCORED" if mode == "scored" else "DESCRIPTIVE",
              "registration_sha256": registration_sha, "grid_hash": GRID_HASH, "decay": decay.digest(),
              "fill_model": fill_model.name, "fill_model_binding": fill_binding,
              "cost_provider": type(cost_provider).__module__ + "." + type(cost_provider).__qualname__, "days": days, "hazard_per_minute": hazard_per_minute,
              "strategies": totals}
    result["digest"] = digest(result)
    return result
