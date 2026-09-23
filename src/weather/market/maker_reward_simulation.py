"""Offline what-if scenarios using the canonical liquidity-reward calculator.

Every changed input is an assumption. This module cannot create venue evidence,
cash receipts, paper fills, or trading authority.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
import hashlib
import json

from weather.market.maker_incentive_feasibility import (
    AdjustedMidpoint, Book, BuyQuote, Campaign, Capital, CompetitionScenario,
    EpochPayoutModel, Evidence, MarketTerms, ScoringRules, assess_buy_plan,
)
from weather.market.maker_opportunity_inputs import number, validate_packet
from weather.schema_registry import schema_version

D = Decimal
FORMULA_URL = "https://docs.polymarket.com/programs/liquidity-rewards"
PAYOUT_URL = "https://help.polymarket.com/en/articles/13364466-liquidity-rewards"
COLLATERAL = "eip155:137/erc20:0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb"
REWARD = "eip155:137/erc20:0x2791bca1f2de4661ed88a30c99a7a9449aa84174"
HOURS = (D(".5"), D(2), D(6), D(24))


@dataclass(frozen=True)
class Simulation:
    plan: str = "YES"
    midpoint: str = "0.40"
    yes_price: str = "0.39"
    no_price: str = "0.59"
    yes_shares: str = "20"
    no_shares: str = "20"
    yes_best_bid: str = "0.39"
    yes_best_ask: str = "0.41"
    no_best_bid: str = "0.59"
    no_best_ask: str = "0.61"
    tick: str = "0.01"
    exchange_minimum: str = "5"
    reward_minimum: str = "20"
    max_spread_cents: str = "3"
    other_q: str = "200"
    yes_remaining: str = "1"
    no_remaining: str = "1"
    participation: str = "1"
    pool: str = "44"
    payout_minimum: str = "1"
    reward_to_collateral: str = "1"
    operating_cost: str = "0.25"
    exit_loss_per_filled_share: str = "0.02"
    wallet: str = "100"
    order_cap: str = "10"
    cleanup: str = "10"


def capture_presets(packet):
    """Bounded, validated observations; the ordinary midpoint is only a seed."""
    validated = validate_packet(packet)
    output = []
    for row in validated["rows"]:
        reward, books = row["rewards"], row["books"]
        if not reward or len(reward["rewards_config"]) != 1:
            continue
        allocation = reward["rewards_config"][0]
        if "eip155:137/erc20:" + allocation["asset_address"].lower() != REWARD:
            continue
        yes, no = books["YES"], books["NO"]
        minimum = max(yes["minimum_shares"], number(reward["rewards_min_size"], "minimum"))
        values = {
            "yes_price": yes["best_bid"], "no_price": no["best_bid"],
            "yes_shares": minimum, "no_shares": minimum,
            "yes_best_bid": yes["best_bid"], "yes_best_ask": yes["best_ask"],
            "no_best_bid": no["best_bid"], "no_best_ask": no["best_ask"],
            "tick": yes["tick"], "exchange_minimum": yes["minimum_shares"],
            "reward_minimum": reward["rewards_min_size"],
            "max_spread_cents": reward["rewards_max_spread"],
            "pool": allocation["rate_per_day"],
            "midpoint": (yes["best_bid"] + yes["best_ask"]) / 2,
        }
        output.append({
            "label": row["selection"]["location_id"],
            "condition_id": row["selection"]["condition_id"],
            "observed_at": validated["as_of"].isoformat(),
            "terms_sha256": row["terms_evidence"]["sha256"],
            "seed": {key: str(value) for key, value in values.items()},
            "assumed_seed_fields": ["midpoint", "pool", "yes_shares", "no_shares"],
            "seed_note": "Ordinary midpoint seeds an assumed adjusted midpoint; configured daily rate seeds an assumed whole-day pool. Neither qualifies venue inputs.",
        })
    return output


def simulate(settings: Simulation):
    """Evaluate constant conditions in a declared hypothetical 1,440-sample day."""
    if not isinstance(settings, Simulation) or settings.plan not in {"YES", "NO", "BOTH"}:
        raise ValueError("simulation:invalid_plan")
    values = asdict(settings)
    v = {key: number(value, key) for key, value in values.items() if key != "plan"}
    for key in ("yes_remaining", "no_remaining", "participation"):
        if v[key] > 1:
            raise ValueError(key + ":fraction")
    if v["reward_to_collateral"] <= 0:
        raise ValueError("reward_to_collateral:positive_required")
    # Decimal scoring and all cash algebra are independent of caller context.
    with localcontext() as context:
        context.prec = 80
        return _simulate(settings.plan, values, v)


def _simulate(plan, values, v):
    at = datetime(2100, 1, 1, tzinfo=timezone.utc)
    end = at + timedelta(days=1)
    digest = hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    ev = Evidence(digest, at)
    event, condition = "highest-temperature-in-toronto-on-january-1-2100", "0x" + "1" * 64
    market = MarketTerms(
        "polymarket_global", event, condition, "1", "2", COLLATERAL,
        v["exchange_minimum"], v["tick"], v["reward_minimum"], v["max_spread_cents"],
        ev, True, "shares", "Simulation assumption; no venue order",
    )
    books = {outcome: Book(event, condition, token, v[prefix + "_best_bid"], v[prefix + "_best_ask"], ev)
             for outcome, token, prefix in (("YES", "1", "yes"), ("NO", "2", "no"))}
    midpoint = AdjustedMidpoint(v["midpoint"], "size_cutoff_adjusted", "SIMULATION_ASSUMPTION", v["reward_minimum"], digest, digest, ev)
    rules = ScoringRules(D(1), D(3), D(".1"), D(".9"), ev)
    campaign = Campaign("SIMULATION", condition, REWARD, at, end, "ASSUMED_UTC_DAY", v["pool"], ev)
    capital = Capital(COLLATERAL, v["wallet"], D(0), D(0), v["wallet"], D(0), D(0),
                      v["cleanup"], v["order_cap"], v["wallet"], v["wallet"], v["wallet"])
    outcomes = ("YES", "NO") if plan == "BOTH" else (plan,)
    quotes = [BuyQuote(outcome, "1" if outcome == "YES" else "2", v[outcome.lower() + "_price"], v[outcome.lower() + "_shares"]) for outcome in outcomes]
    remaining = {outcome: v[outcome.lower() + "_remaining"] for outcome in outcomes}
    inventory_cost = sum((quote.price * quote.shares * (1 - remaining[quote.outcome]) for quote in quotes), D(0))
    remaining_reserves = sum((quote.price * quote.shares * remaining[quote.outcome] for quote in quotes), D(0))
    filled_shares = sum((quote.shares * (1 - remaining[quote.outcome]) for quote in quotes), D(0))
    cost = v["operating_cost"] + filled_shares * v["exit_loss_per_filled_share"]
    rows, first = [], None
    for hours in HOURS:
        # Participation is an assumed fraction of the selected window's samples.
        payout = EpochPayoutModel("HYPOTHETICAL_DAY", "SIMULATION", condition, REWARD, at, end,
                                  v["pool"], 1440, int(hours * 60), v["payout_minimum"], ev)
        scenario = CompetitionScenario("ASSUMED_CONSTANT_COMPETITION", v["other_q"], v["other_q"],
                                       v["participation"], v["yes_remaining"], v["no_remaining"])
        result = assess_buy_plan(
            market=market, yes_book=books["YES"], no_book=books["NO"], midpoint=midpoint,
            rules=rules, campaigns=[campaign], quotes=quotes, capital=capital, scenarios=[scenario],
            as_of=at, horizon_end=at + timedelta(hours=float(hours)), max_input_age=timedelta(0),
            max_book_age=timedelta(0), max_book_skew=timedelta(0), other_own_orders_absent=True, payout_model=payout,
        )
        first = first or result
        estimate = result["scenarios"][0]
        gross = estimate["conditional_reward_amount_range"][0]
        # Only for a completed, sole-income hypothetical day. Other markets or
        # late evidence require account-wide aggregation, never this threshold.
        paid = None if gross is None else (gross if gross >= v["payout_minimum"] else D(0))
        rows.append({
            "hours": hours, "sample_share": estimate["conditional_sample_share_range"][0],
            "gross_reward": gross, "modeled_day_payout": paid,
            "net_collateral": None if paid is None else paid * v["reward_to_collateral"] - cost,
            "zero_payment_net_collateral": -cost,
            "required_gross_reward_to_break_even": max(v["payout_minimum"], cost / v["reward_to_collateral"]) if cost else D(0),
        })
    return {
        "schema_version": schema_version("maker_reward_simulation"),
        "mode": "hypothetical_liquidity_reward_simulation",
        "input_sha256": digest, "inputs": values,
        "formula_sources": [FORMULA_URL, PAYOUT_URL],
        "assumptions": {
            "midpoint": "User-assumed size-cutoff-adjusted midpoint, not a measured venue midpoint.",
            "epoch": "One hypothetical UTC day with 1,440 nonempty, equally weighted samples. Other makers supply nonempty samples outside our participation.",
            "pool": "User-assumed whole-day pool, not an observed accrued allocation.",
            "payout_threshold": "Completed day; this scenario is the account's only reward income. No carry between days.",
            "competition": "Sum of OTHER makers' individually computed Q_min during our modeled samples.",
            "multiplier": "Common normalized b=1; competitors use the same score scale.",
            "fills": "Chosen remainder persists throughout participation; filled inventory stays funded alongside remaining order commitments.",
            "conversion": "Explicit assumed pUSD per reward token, not measured exchange parity.",
            "costs": "Operating cost plus filled shares times all-in exit loss, including fees/adverse selection. No rebates, settlement gain or spread capture assumed.",
        },
        "modeled_feasible": first["incentive_feasible"], "blockers": first["blockers"],
        "submitted_side_scores": first["side_scores"], "submitted_q_min": first["own_q_min"],
        "remaining_q_min": first["scenarios"][0]["remaining_order_q"],
        "capital": {"submitted_reservation": first["simultaneous_reservation"],
                    "filled_inventory_cost": inventory_cost, "remaining_order_reserves": remaining_reserves,
                    "total_with_cleanup": inventory_cost + remaining_reserves + v["cleanup"]},
        "modeled_cost_collateral": cost, "horizons": rows,
        "paid_rewards": None, "realized_pnl": None, "live_order_authority": False,
    }
