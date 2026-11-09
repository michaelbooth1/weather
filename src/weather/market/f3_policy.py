"""Pure T5-R simulation policy. Gate equivalence is for reconciled clean states only.

At F2 c4c3216b1c98f74fd7dc1716c6cf8e45b70beb4f, lfc_capital.py:580-589
checks bridge existence, ledger halt/mismatch, unknown outgoing activity and
blocking legacy activity. Lines 598-605 check capital_cash_changed (unexplained
debit) and limit spendable cash for unrecorded/quarantined incoming cash, which
can cause capital_spendable_cash at :611. These real accounting checks are
replaced by explicit SimCashState assertions; violations raise F3NotReconciled
before any decision. The ordinary segregated-cash comparison is still ported.
No equivalence is claimed outside that domain. Rewards/rebates contribute zero
to available_gains: that input contains proved retained redemption gains only.

The active F2 hold path (lfc_f2_controller.py:186-196 -> re1_attended.py:75-133)
requotes drift and retires a fresh book refusal. The legacy midpoint_drift
exception in mm_stage2_hold.py:202-210 is not the active F2 path.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import fields, is_dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Context, Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR, localcontext
from functools import wraps
import math
from types import MappingProxyType
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

from weather.market.f3_types import (
    BandCandidate, BandDayUsage, BookState, CapitalState, EnvelopeCell,
    F3NotReconciled, F3Params, GateResult, GuardHit, NwpSchedule, PortfolioState,
    QuotePair, Refusal, Selection, SimCashState, Terms, TokenBook, UniverseCity,
    Window, policy_from_mapping,
)
from weather.market.reward_share_estimate import (
    order_score as float_order_score, q_min as float_q_min, share_of, side_score,
)

POLICY_VERSION = "f3_policy_v1"
D = Decimal
ZERO = D(0)


def _context(fn):
    @wraps(fn)
    def call(*args, **kwargs):
        with localcontext(Context(prec=28)):
            return fn(*args, **kwargs)
    return call


def _utc(now: datetime) -> datetime:
    if now.tzinfo is None or now.utcoffset() != timedelta(0):
        raise ValueError("timezone-aware UTC required")
    return now.astimezone(timezone.utc)


def horizon_allowed(city: UniverseCity, event_date_local: date, now_utc: datetime, params: F3Params) -> bool:
    """F2 market-local DTE calculation, with the supplied universe identity."""
    return (event_date_local - _utc(now_utc).astimezone(ZoneInfo(city.timezone)).date()).days in params.local_event_dte


def stratum(city: UniverseCity, family: str, event_date_local: date, now_utc: datetime, params: F3Params) -> str | None:
    local = _utc(now_utc).astimezone(ZoneInfo(city.timezone))
    if family == "highest" and horizon_allowed(city, event_date_local, now_utc, params) and local.time() < params.retire_local_time:
        return "H-PRE"
    return None


def _number(value):
    try:
        number = D(str(value))
    except (InvalidOperation, ValueError):
        return Refusal("invalid_number")
    if isinstance(value, bool) or not number.is_finite() or not math.isfinite(float(number)):
        return Refusal("invalid_number")
    return number


def _levels(rows):
    result = []
    for row in rows:
        p, s = _number(row.price), _number(row.size)
        if isinstance(p, Refusal) or isinstance(s, Refusal):
            return Refusal("invalid_number")
        if not 0 < p < 1 or s <= 0:
            return Refusal("invalid_book")
        result.append((p, s))
    return tuple(result) if result else Refusal("one_sided_book")


def _books(book):
    if book.yes is None or book.no is None:
        return Refusal("one_sided_book")
    result = []
    for rows in (book.yes.bids, book.yes.asks, book.no.bids, book.no.asks):
        levels = _levels(rows)
        if isinstance(levels, Refusal):
            return levels
        result.append(levels)
    return tuple(result)


@_context
def adjusted_mid(book: TokenBook, min_size: Decimal) -> Decimal | None:
    bids = [row.price for row in book.bids if row.size >= min_size]
    asks = [row.price for row in book.asks if row.size >= min_size]
    return (max(bids) + min(asks)) / 2 if bids and asks else None


def _rate_ok(rate, floor):
    return rate > floor if floor == 0 else rate >= floor


def _float_pair(mid, prices, size, maximum, minimum, bids, asks, *, subtract=False, legs=(0, 1)):
    scores = []
    for leg, (levels, own_price) in enumerate(((bids, prices[0]), (asks, 1 - prices[1]))):
        if subtract:
            aggregate = {}
            for p, s in levels:
                aggregate[p] = aggregate.get(p, ZERO) + s
            if leg in legs:
                aggregate[own_price] = max(ZERO, aggregate.get(own_price, ZERO) - size)
            levels = [(p, s) for p, s in aggregate.items() if s > 0]
        scores.append(side_score([(float(p), float(s)) for p, s in levels], float(mid), float(maximum), float(minimum))[0])
    distances = ((mid - prices[0]) * 100, (1 - mid - prices[1]) * 100)
    own = float_q_min(*(float_order_score(float(size), float(d), float(maximum), float(minimum)) if i in legs else 0
                       for i, d in enumerate(distances)), float(mid))
    return own, share_of(own, sum(scores) / 2)


@_context
def quote_pair(book: BookState, terms: Terms, params: F3Params) -> QuotePair | Refusal:
    if book.state != "known":
        return Refusal("G-STALE")
    values = [terms.min_size, terms.max_spread_cents, terms.rate_daily_pusd,
              book.yes.tick if book.yes else params.tick_pusd,
              params.per_order_cap_pusd, params.per_band_cap_pusd, params.shares_per_leg,
              params.quote_offset_pusd, *params.requote_distance_cents, params.min_reward_rate]
    converted = list(map(_number, values))
    if any(isinstance(v, Refusal) for v in converted):
        return Refusal("invalid_number")
    minimum, maximum, rate, step, order_cap, band_cap, size, offset, low, high, floor = converted
    legs = {("YES",): (0,), ("NO",): (1,), ("YES", "NO"): (0, 1)}.get(tuple(params.tokens), ())
    if not D(".005") <= offset <= D(".05") or not D(".5") <= low <= high <= 6 or not legs:
        return Refusal("unsupported_quote_policy")
    if size not in (20, 30, 40, 50, 75):
        return Refusal("invalid_treatment_size")
    if not 0 < minimum <= size:
        return Refusal("reward_minimum_outside_treatment")
    if maximum < 3 or not _rate_ok(rate, floor):
        return Refusal("reward_terms_outside_treatment")
    if step != D(".01") or (book.no is not None and book.no.tick != step):
        return Refusal("unsupported_tick")
    if terms.post_only_available is not True:
        return Refusal("post_only_unavailable")
    if not (0 < order_cap <= D(".8") * size and 0 < band_cap <= min(size, 75)):
        return Refusal("invalid_capital_ceiling")
    books = _books(book)
    if isinstance(books, Refusal):
        return books
    yb, ya, nb, na = books
    for bids, asks in ((yb, ya), (nb, na)):
        if any(p % step for p, _ in (*bids, *asks)):
            return Refusal("off_tick_book")
        spread = min(p for p, _ in asks) - max(p for p, _ in bids)
        if spread <= 0:
            return Refusal("crossed_book")
        if spread > D(".06"):
            return Refusal("spread_too_wide")
    mid = adjusted_mid(book.yes, minimum)
    if mid is None:
        return Refusal("no_size_adjusted_midpoint")
    if not D(".20") <= mid <= D(".80"):
        return Refusal("midpoint_outside_treatment")
    yes, no = ((v / step).to_integral_value(rounding=ROUND_FLOOR) * step for v in (mid - offset, 1 - mid - offset))
    for buy, asks in ((yes, ya), (no, na)):
        if buy <= 0 or min(p for p, _ in asks) - buy < step:
            return Refusal("would_cross_or_violate_touch_buffer")
    prices = (yes, no)
    reserve = size * sum((prices[i] for i in legs), ZERO)
    if max(prices[i] for i in legs) * size > order_cap or reserve > band_cap:
        return Refusal("capital_ceiling_exceeded")
    distances = ((mid - yes) * 100, (1 - mid - no) * 100)
    if any(not low <= distances[i] <= high or distances[i] >= maximum for i in legs):
        return Refusal("outside_leave_alone_window")
    own, share = _float_pair(mid, prices, size, maximum, minimum, yb, ya, legs=legs)
    pair = QuotePair(mid, yes, no, size, reserve, distances, D(str(own)), share)
    if any(not params.leg_price_range[0] <= prices[i] <= params.leg_price_range[1] for i in legs):
        return Refusal("leg_price_outside_range")
    return check_book(book, terms, mid=mid, size=size, share=share, params=params) or pair


@_context
def check_book(book: BookState, terms: Terms, *, mid: Decimal, size: Decimal, share: float, params: F3Params) -> Refusal | None:
    if not _rate_ok(terms.rate_daily_pusd, params.min_reward_rate) or terms.max_spread_cents < 3:
        return Refusal("reward_rate_or_terms")
    if not D(".20") <= mid <= D(".80"):
        return Refusal("midpoint_outside_treatment")
    if not params.share_many_range[0] <= D(str(share)) <= params.share_many_range[1]:
        return Refusal("share_many_outside_range")
    books = _books(book)
    if isinstance(books, Refusal):
        return books
    yb, ya, nb, na = books
    for bids, asks in ((yb, ya), (nb, na)):
        if not 0 < min(p for p, _ in asks) - max(p for p, _ in bids) <= D(".06"):
            return Refusal("spread_too_wide")
    reach = terms.max_spread_cents / 100
    depth = min(sum((s for p, s in yb if mid - reach <= p <= mid), ZERO),
                sum((s for p, s in ya if mid <= p <= mid + reach), ZERO))
    return Refusal("thin_book_depth") if depth < max(params.min_book_depth, size) else None


@_context
def observe_held(book: BookState, terms: Terms, pair: QuotePair, params: F3Params) -> str:
    """Active F2 observe + check_book, rather than the legacy hold-only helper."""
    if (book.state != "known" or pair.size not in (20, 30, 40, 50, 75) or terms.min_size > pair.size or
            terms.min_size <= 0 or terms.max_spread_cents <= 0 or not _rate_ok(terms.rate_daily_pusd, params.min_reward_rate)):
        return "retire"
    books = _books(book)
    if isinstance(books, Refusal):
        return "retire"
    yb, ya, nb, na = books
    if any(max(p for p, _ in bids) >= min(p for p, _ in asks) for bids, asks in ((yb, ya), (nb, na))):
        return "retire"
    mid = adjusted_mid(book.yes, terms.min_size)
    if mid is None:
        return "retire"
    _, share = _float_pair(mid, (pair.yes_buy, pair.no_buy), pair.size, terms.max_spread_cents,
                           terms.min_size, yb, ya, subtract=True)
    if check_book(book, terms, mid=mid, size=pair.size, share=share, params=params):
        return "retire"
    low, high = params.requote_distance_cents
    distances = ((mid - pair.yes_buy) * 100, (1 - mid - pair.no_buy) * 100)
    return "requote" if any(not low <= d <= high for d in distances) else "hold"


def order_score(size: Decimal, distance_cents: Decimal, max_spread_cents: Decimal, min_size: Decimal) -> Decimal:
    # Decimal lines ported from T1; no market -> backtesting import edge.
    if size < min_size or distance_cents >= max_spread_cents:
        return ZERO
    return size * ((max_spread_cents - distance_cents) / max_spread_cents) ** 2


def q_min(q1: Decimal, q2: Decimal, mid: Decimal) -> Decimal:
    both = min(q1, q2)
    return max(both, max(q1, q2) / D(3)) if D(".10") <= mid <= D(".90") else both


@_context
def pair_score(pair: QuotePair, terms: Terms) -> Decimal:
    return q_min(*(order_score(pair.size, d, terms.max_spread_cents, terms.min_size) for d in pair.distances_cents), pair.adjusted_mid)


@_context
def competitor_q(book: BookState, mid: Decimal, terms: Terms, own: Sequence[tuple[str, Decimal, Decimal]] = ()) -> Decimal:
    """T1 aggregate upper bound over four displayed sides, divided by two.

    Own entries are native BUY orders (YES/NO, price, remaining shares).
    Subtract each from its native bids and its complementary mirrored asks,
    after aggregating duplicate price rows, clamping missing display at zero.
    """
    if book.state != "known" or book.yes is None or book.no is None:
        return ZERO
    total = ZERO
    for outcome, token in (("YES", book.yes), ("NO", book.no)):
        for side, rows in (("bids", token.bids), ("asks", token.asks)):
            aggregate = defaultdict(lambda: ZERO)
            for row in rows:
                aggregate[row.price] += row.size
            for native_outcome, p, size in own:
                if native_outcome not in ("YES", "NO") or size < 0:
                    raise ValueError("own BUY order")
                if side == "bids" and outcome == native_outcome:
                    aggregate[p] = max(ZERO, aggregate[p] - size)
                elif side == "asks" and outcome != native_outcome:
                    aggregate[1 - p] = max(ZERO, aggregate[1 - p] - size)
            for p, size in aggregate.items():
                yes_p = p if outcome == "YES" else 1 - p
                total += order_score(size, abs(yes_p - mid) * 100, terms.max_spread_cents, terms.min_size)
    return total / 2


def nwp_windows(schedule: NwpSchedule, utc_day: date) -> tuple[Window, ...]:
    start = datetime.combine(utc_day, time(), timezone.utc)
    end = start + timedelta(days=1)
    # Derive cycle dates from the requested availability date, including IFS 18Z.
    rows = []
    before, after = timedelta(minutes=schedule.before_minutes), timedelta(minutes=schedule.after_minutes)
    for delta in range(-2 - schedule.after_minutes // 1440, 2 + schedule.before_minutes // 1440):
        cycle_day = utc_day + timedelta(days=delta)
        for release in schedule.releases:
            at = datetime.combine(cycle_day + timedelta(days=release.day_offset), release.available_utc, timezone.utc)
            if at - before < end and at + after > start:
                rows.append(Window(at - before, at + after, f"{release.model}:{release.cycle_utc}"))
    return tuple(sorted(rows, key=lambda w: (w.start_utc, w.source)))


def guards(cand: BandCandidate, *, now_utc: datetime, windows: Sequence[Window], city: UniverseCity, params: F3Params) -> tuple[GuardHit, ...]:
    now = _utc(now_utc)
    hits = []
    terms = cand.terms
    if terms is None or terms.min_size != 20 or terms.max_spread_cents < 3:
        hits.append(GuardHit("G-TERMS", "no_post"))
    if terms and (terms.fee_taker_coefficient, terms.fee_maker, terms.rebate_fraction) != (
            params.fee_expected.taker_coefficient, params.fee_expected.maker, params.fee_expected.rebate_fraction):
        hits.append(GuardHit("G-FEE", "exclude_day"))
    if cand.book.state != "known":
        hits.append(GuardHit("G-STALE", "no_post"))
    if any(_utc(w.start_utc) <= now < _utc(w.end_utc) for w in windows):
        hits.append(GuardHit("G-NWP", "cancel"))
    local = now.astimezone(ZoneInfo(city.timezone))
    if local.date() == cand.event_date_local - timedelta(days=1) and local.time() >= params.retire_local_time:
        hits.append(GuardHit("G-MID", "retire"))
    if cand.possible is False:
        hits.append(GuardHit("G-POSS", "cancel"))
    if local.date() == cand.event_date_local and cand.obs is not None:
        if cand.possible is False:
            hits.append(GuardHit("G-OBS", "retire", "ruled_out"))
        relevant = (cand.obs.running_extreme_bin, *cand.obs.neighbour_bins)
        if cand.condition_id in relevant:
            low, high = params.g_obs.window_minutes
            for obs in cand.obs.routine_obs_utc:
                if _utc(obs) + timedelta(minutes=low) <= now <= _utc(obs) + timedelta(minutes=high):
                    hits.append(GuardHit("G-OBS", "cancel", "pull_or_widen_to_3c"))
                    break
    return tuple(hits)


@_context
def value(cand: BandCandidate, pair: QuotePair, envelope: Mapping[str, EnvelopeCell], params: F3Params) -> tuple[Decimal, Decimal]:
    cell = envelope.get(cand.cell)
    if cell is None or not cell.validated or cand.terms is None:
        return ZERO, ZERO
    own = pair_score(pair, cand.terms)
    competing = competitor_q(cand.book, pair.adjusted_mid, cand.terms)
    if cell.cell != cand.cell or cell.shape not in ("additive", "proportional"):
        raise ValueError("envelope cell/shape")
    coefficient = cell.a_q80 if cell.shape == "additive" else cell.kappa_q80
    if coefficient is None or not coefficient.is_finite() or coefficient < 0:
        raise ValueError("envelope coefficient")
    response = coefficient if cell.shape == "additive" else coefficient * own
    denominator = own + competing + response
    reward = cand.terms.rate_daily_pusd * own / denominator if own > 0 and denominator > 0 else ZERO
    return reward, reward / pair.reserve_pusd if pair.reserve_pusd > 0 else ZERO


def _native(value: Decimal, *, ceil=False) -> int:
    if not isinstance(value, D) or not value.is_finite() or value < 0:
        raise ValueError("nonnegative finite Decimal required")
    scaled = value * 1_000_000
    if ceil:
        return int(scaled.to_integral_value(rounding=ROUND_CEILING))
    if scaled != scaled.to_integral_value():
        raise ValueError("capital_native_precision")
    return int(scaled)


def _reconciled(capital, cash):
    if not isinstance(cash, SimCashState):
        raise F3NotReconciled("cash")
    if cash.available != cash.expected:
        raise F3NotReconciled("cash.available")
    if cash.quarantined_after_bridge != 0:
        raise F3NotReconciled("quarantined_after_bridge")
    for field, expected in (("bridge_exists", True), ("ledger_halted", False), ("ledger_mismatches", False),
                            ("unknown_outgoing_activity", False), ("blocking_legacy_activity", False), ("unknown_activity", False)):
        if getattr(cash, field) is not expected:
            raise F3NotReconciled(field)
    if capital.external != 0:
        raise F3NotReconciled("external")
    # Reward/rebate pools cannot be relabelled as retained redemption gains.
    if capital.available_gains > capital.profit:
        raise F3NotReconciled("available_gains")


def sleeve_charge(*, loss, inventory, resting, costs, available_gains, basis) -> tuple[Decimal, Decimal]:
    if not isinstance(basis, str) or basis not in ("gross", "net_of_retained_gains"):
        raise ValueError("capital_loss_basis")
    offset = min(loss + costs, available_gains) if basis == "net_of_retained_gains" else ZERO
    return inventory + resting + loss + costs - offset, offset


def _result(ok, code=None, figures=None):
    return GateResult(ok, code, MappingProxyType({k: D(v) for k, v in (figures or {}).items()}))


@_context
def gate(capital: CapitalState, *, reserve: Decimal, own_resting: Decimal, cash: SimCashState | None) -> GateResult:
    _reconciled(capital, cash)  # Domain violations are never policy decisions.
    try:
        funding, inventory, resting, losses, costs, gains, profit, incentives = (
            _native(v) for v in (capital.funding, capital.inventory, capital.resting, capital.losses,
                                capital.costs, capital.available_gains, capital.profit, capital.incentives))
        proposed, own, available = _native(reserve, ceil=True), _native(own_resting), _native(cash.available)
    except ValueError as exc:
        if str(exc) == "capital_native_precision":
            return _result(False, str(exc))
        raise
    charged, offset = sleeve_charge(loss=losses, inventory=inventory, resting=resting, costs=costs,
                                    available_gains=gains, basis=capital.basis)
    if own > resting:
        return _result(False, "capital_own_reserve")
    if charged - own + proposed > funding:
        return _result(False, "capital_total_ceiling")
    if available - (profit + incentives - offset) < resting - own + proposed:
        return _result(False, "capital_spendable_cash")
    return _result(True, figures=dict(funding_native=funding, charged_native=charged,
                                    resting_reserve_native=resting, retained_gains_offset_native=offset))


@_context
def daily_gate(usage: BandDayUsage, *, reserve: Decimal, own_resting: Decimal, cap: Decimal) -> GateResult:
    try:
        filled, resting, unmapped, ceiling = map(_native, (usage.filled, usage.resting, usage.unmapped_legacy, cap))
        proposed, own = _native(reserve, ceil=True), _native(own_resting, ceil=True)
    except ValueError as exc:
        if str(exc) == "capital_native_precision":
            return _result(False, str(exc))
        raise
    if not 0 < ceiling <= 300_000_000:
        return _result(False, "band_day_cap")
    if own > resting:
        return _result(False, "band_day_own_reserve")
    if filled + resting - own + proposed > ceiling:
        return _result(False, "per_band_daily_filled_cap")
    return _result(True, figures=dict(filled_native=filled, resting_native=resting, unmapped_legacy_native=unmapped,
        cap_native=ceiling, prospective_native=proposed, remaining_native=ceiling - filled - resting + own - proposed))


def per_market_cash_ok(open_notional: Decimal, new_reserve: Decimal, cash: Decimal) -> bool:
    return open_notional + new_reserve <= cash


@_context
def select(cands: Sequence[BandCandidate], state: PortfolioState, *, now_utc: datetime, windows: Sequence[Window],
           universe: Mapping[str, UniverseCity], envelope: Mapping[str, EnvelopeCell], params: F3Params) -> Selection:
    _reconciled(state.capital, state.cash)
    now = _utc(now_utc)
    rows, refusals = [], Counter()
    for cand in cands:
        if cand.cfd_key in state.quoted_cfds:
            refusals["f3_cfd_already_quoted"] += 1
            continue
        city = universe[cand.city]
        if stratum(city, cand.family, cand.event_date_local, now, params) != "H-PRE":
            refusals["f3_not_h_pre"] += 1
            continue
        if {c.lower() for c in cand.event_condition_ids} & {c.lower() for c in state.held_conditions}:
            refusals["f3_event_held"] += 1
            continue
        hits = guards(cand, now_utc=now, windows=windows, city=city, params=params)
        if hits:
            refusals.update(hit.guard for hit in hits)
            continue
        pair = quote_pair(cand.book, cand.terms, params)
        if isinstance(pair, Refusal):
            refusals[pair.code] += 1
            continue
        reward, score = value(cand, pair, envelope, params)
        if reward < params.min_expected_reward_pusd_per_day:
            refusals["f3_reward_below_floor"] += 1
            continue
        rows.append((-score, cand.condition_id, cand, pair, score))
    rows.sort(key=lambda r: r[:2])
    picks, seen, prospective = [], set(), ZERO
    clusters = Counter(state.active_bands.values())
    for _, _, cand, pair, score in rows:
        if cand.cfd_key in seen:
            continue
        if len(state.active_bands) + len(picks) >= params.max_concurrent_bands:
            refusals["f3_concurrency_cap"] += 1
            break
        if clusters[cand.cluster] >= params.max_bands_per_cluster:
            refusals["f3_cluster_cap"] += 1
            continue
        usage = state.band_day_usage.get((cand.band_key, now.date().isoformat()), BandDayUsage(ZERO, ZERO))
        daily = daily_gate(usage, reserve=pair.reserve_pusd, own_resting=ZERO, cap=params.per_band_daily_filled_cap_pusd)
        if not daily.ok:
            refusals[daily.code] += 1
            refusals["gate_refusals"] += 1
            continue
        capital = replace(state.capital, resting=state.capital.resting + prospective)
        money = gate(capital, reserve=pair.reserve_pusd, own_resting=ZERO, cash=state.cash)
        if not money.ok:
            refusals[money.code] += 1
            refusals["gate_refusals"] += 1
            continue
        if not per_market_cash_ok(state.per_market_open.get(cand.condition_id, ZERO), pair.reserve_pusd, state.cash.available):
            refusals["f3_per_market_cash"] += 1
            continue
        picks.append((cand, pair, score))
        clusters[cand.cluster] += 1
        seen.add(cand.cfd_key)
        prospective += pair.reserve_pusd
    return Selection(tuple(picks), MappingProxyType(dict(refusals)))


def _config_value(value):
    if is_dataclass(value):
        return {f.name: _config_value(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {k: _config_value(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_config_value(v) for v in value]
    if isinstance(value, D):
        return str(value)
    return value.strftime("%H:%M") if isinstance(value, time) else value


def params_from_f2_policy(policy_raw: Mapping[str, object], *, f2_git_sha: str, f2_policy_sha256: str) -> F3Params:
    """Copy mandatory F2 economic fields; never fall back to an example basis."""
    for source, width in ((f2_git_sha, 40), (f2_policy_sha256, 64)):
        if not isinstance(source, str) or len(source) != width or any(c not in "0123456789abcdef" for c in source):
            raise ValueError("frozen F2 source hash required")
    row = _config_value(F3Params())
    keys = ("local_event_dte", "tokens", "shares_per_leg", "tick_pusd", "quote_offset_pusd",
            "requote_distance_cents", "leg_price_range", "share_many_range", "min_reward_rate", "min_book_depth",
            "per_order_cap_pusd", "per_band_cap_pusd", "per_band_daily_filled_cap_pusd", "fill_cooldown_seconds",
            "on_first_band_fill", "replace_retired_band", "sleeve_loss_basis")
    try:
        row.update({key: policy_raw[key] for key in keys})
        row["sleeve_ceiling_pusd"] = policy_raw["owner_funding_ceiling_pusd"]
    except KeyError as exc:
        raise ValueError("missing frozen F2 economic field: " + str(exc)) from exc
    row["f2_source"] = dict(git_sha=f2_git_sha, policy_sha256=f2_policy_sha256, freeze_receipt_sha256=None)
    return policy_from_mapping(row)
