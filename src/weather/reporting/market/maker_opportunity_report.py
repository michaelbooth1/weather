"""Offline report for a frozen shortlist's captured public maker evidence.

The initial adapter qualifies order/capital inputs. Missing venue-adjusted
midpoints and epoch semantics remain explicit blockers, never fitted defaults.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_CEILING, localcontext
import hashlib
import json
from pathlib import Path
import re

from weather.market.exchange_economics import (
    PUSD_COLLATERAL_PROXY_ADDRESS, _rule_document_semantic_checks,
)
from weather.market.maker_incentive_feasibility import (
    Book, BuyQuote, Capital, CompetitionScenario, Evidence, FeasibilityInputError,
    MarketTerms, ScoringRules, assess_buy_plan,
)
from weather.market.maker_opportunity_capture import read_json, write_new_json
from weather.market.maker_opportunity_inputs import number, timestamp, validate_packet
from weather.market.market_registry import spec_for_slug
from weather.paths import data_path
from weather.schema_registry import schema_version

D = Decimal
ORDER_RULE_URL = "https://docs.polymarket.com/trading/place-orders.md"
REWARD_RULE_URL = "https://docs.polymarket.com/programs/liquidity-rewards.md"
CONTRACT_URL = "https://docs.polymarket.com/resources/contracts.md"


def json_value(value):
    if is_dataclass(value):
        return json_value(asdict(value))
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_value(item) for item in value]
    return value


def evidence(raw):
    return Evidence(raw["response_sha256"], timestamp(raw["retrieved_at_utc"]))


def _normalize(text):
    return " ".join(re.sub(r"[\x60*]", "", text.lower()).split())


def _source_qualifiers(rules):
    order_text = _normalize(rules[ORDER_RULE_URL]["text"])
    return {
        "clob_minimum_unit_shares": "min_order_size is the minimum number of shares" in order_text,
        "share_precision_table": all(label in order_text for label in ("tick size", "price decimals", "size decimals", "amount decimals")),
        "collateral_contract": all(_rule_document_semantic_checks(
            CONTRACT_URL.removesuffix(".md"), rules[CONTRACT_URL]["text"],
        ).values()),
        "liquidity_rule_surface": all(_rule_document_semantic_checks(
            REWARD_RULE_URL.removesuffix(".md"), rules[REWARD_RULE_URL]["text"],
        ).values()),
    }


def _share_increment(rule_text, tick):
    text = re.sub(r"[\x60*]", "", rule_text)
    rows = re.findall(r"^[ \t]*\|\s*([0-9]+(?:\.[0-9]+)?)\s*\|\s*([0-9]+)\s*\|\s*([0-9]+)\s*\|\s*([0-9]+)\s*\|\s*$", text, re.MULTILINE)
    selected = [int(size) for price, _, size, _ in rows if number(price, "documented_tick") == tick]
    if len(selected) != 1 or not 0 <= selected[0] <= 18:
        raise ValueError("share_precision:selected_tick_missing_or_ambiguous")
    return D(1).scaleb(-selected[0])


def _capital(asset, order_cap, wallet_cap, cleanup):
    return Capital(
        collateral_asset=asset, backed_capital=wallet_cap, inventory_cost=D(0),
        open_order_reserves=D(0), available_collateral=wallet_cap, condition_committed=D(0),
        event_committed=D(0), cleanup_reserve=cleanup, order_cap=order_cap,
        condition_cap=wallet_cap, event_cap=wallet_cap, wallet_cap=wallet_cap,
    )


def _diagnostic_plans(row, rules, as_of, *, order_cap, wallet_cap, cleanup):
    reward = row["rewards"]
    if reward is None:
        return []
    selection, books = row["selection"], row["books"]
    asset = "eip155:137/erc20:" + PUSD_COLLATERAL_PROXY_ADDRESS
    minimum = max(books["YES"]["minimum_shares"], number(reward["rewards_min_size"], "reward_minimum", positive=True))
    # The captured precision table must qualify this exact current book tick.
    increment = _share_increment(rules[ORDER_RULE_URL]["text"], books["YES"]["tick"])
    quantity = minimum.quantize(increment, rounding=ROUND_CEILING)
    if type(row["market"].get("acceptingOrders")) is not bool:
        raise ValueError("gamma:accepting_orders_unqualified")
    market = MarketTerms(
        platform="polymarket_global", event_slug=selection["event_slug"],
        condition_id=selection["condition_id"], yes_token_id=row["tokens"]["YES"],
        no_token_id=row["tokens"]["NO"], collateral_asset=asset,
        order_min_size=books["YES"]["minimum_shares"], order_price_min_tick_size=books["YES"]["tick"],
        rewards_min_size=number(reward["rewards_min_size"], "reward_minimum", positive=True),
        rewards_max_spread_cents=number(reward["rewards_max_spread"], "reward_spread", positive=True),
        evidence=Evidence(row["terms_evidence"]["sha256"], timestamp(row["terms_evidence"]["captured_at_utc"])), accepting_orders=row["market"]["acceptingOrders"],
        order_min_size_unit="shares",
        order_min_size_reference=ORDER_RULE_URL + "#sha256=" + rules[ORDER_RULE_URL]["evidence"]["response_sha256"],
    )
    paired = {
        outcome: Book(market.event_slug, market.condition_id, row["tokens"][outcome],
                      books[outcome]["best_bid"], books[outcome]["best_ask"], evidence(books[outcome]["evidence"]))
        for outcome in ("YES", "NO")
    }
    quotes = {
        outcome: BuyQuote(outcome, row["tokens"][outcome], books[outcome]["best_bid"], quantity)
        for outcome in ("YES", "NO")
    }
    # No reward score is computed with midpoint=None. A normalized multiplier
    # is explicit here and is not asserted to be a measured in-game multiplier.
    scoring = ScoringRules(D(1), D(3), D(".1"), D(".9"), evidence(rules[REWARD_RULE_URL]["evidence"]))
    scenarios = [
        CompetitionScenario("OTHER_Q_0_TO_20_ASSUMED", D(0), D(20), D(1), D(1), D(1)),
        CompetitionScenario("OTHER_Q_20_TO_200_ASSUMED", D(20), D(200), D(1), D(1), D(1)),
        CompetitionScenario("HALF_PARTICIPATION_ASSUMED", D(20), D(200), D(".5"), D(1), D(1)),
        CompetitionScenario("YES_REMAINDER_99_PERCENT_ASSUMED", D(20), D(200), D(1), D(".99"), D(1)),
        CompetitionScenario("NO_SIDE_REMOVED_ASSUMED", D(20), D(200), D(1), D(1), D(0)),
    ]
    output = []
    for label, outcomes in (("YES_BUY_AT_BID", ("YES",)), ("NO_BUY_AT_BID", ("NO",)), ("TWO_BUYS_AT_BIDS", ("YES", "NO"))):
        result = assess_buy_plan(
            market=market, yes_book=paired["YES"], no_book=paired["NO"], midpoint=None,
            rules=scoring, campaigns=[], quotes=[quotes[outcome] for outcome in outcomes],
            capital=_capital(asset, order_cap, wallet_cap, cleanup), scenarios=scenarios,
            as_of=as_of, horizon_end=as_of + timedelta(minutes=30),
            max_input_age=timedelta(days=1), max_book_age=timedelta(seconds=120),
            max_book_skew=timedelta(seconds=15), other_own_orders_absent=True,
        )
        # "Absent" in the calculator means no qualified Campaign was supplied.
        # The API's configured allocations are preserved separately; this is
        # never a claim that the venue has no allocation.
        blockers = result["blockers"]
        result["blockers"] = {**blockers, "rewards": tuple(
            "campaign:interval_unqualified" if blocker == "campaign:absent" else blocker
            for blocker in blockers["rewards"]
        )}
        result["planning_horizon_qualified_for_rewards"] = False
        result["label"] = label
        result["quotes"] = [quotes[outcome] for outcome in outcomes]
        result["order_capital_only"] = True
        output.append(result)
    return output


def _loss_sensitivity(allocations):
    """Algebra for declared hypothetical pools, without prorating a daily rate."""
    output = []
    for allocation in allocations:
        hypothetical_pool = number(allocation["rate_per_day"], "hypothetical_pool")
        if hypothetical_pool == 0:
            continue
        output.append({
            "allocation_id": allocation["id"],
            "reward_asset": "eip155:137/erc20:" + allocation["asset_address"].lower(),
            "hypothetical_whole_epoch_pool": hypothetical_pool,
            "pool_basis": "Scenario only: suppose one entire future epoch pays this many reward-asset units. This is not a qualified epoch pool or accrued amount.",
            "loss_definition": "Total adverse selection, inventory/settlement loss, all fees, forced-exit loss, cash-operation and operating cost, less independently paid rebates; all expressed in this same asset.",
            "cost_scenarios": [
                {"all_in_net_cost": cost, "whole_epoch_share_to_break_even": cost / hypothetical_pool,
                 "whole_epoch_share_for_one_asset_unit_reward": D(1) / hypothetical_pool,
                 "zero_payment_net": -cost}
                for cost in (D(0), D(".25"), D(1), D(2), D(5), D(10))
            ],
            "assumed_epoch_dates": None, "assumed_earning_duration": None,
            "fiat_payout_minimum_qualified": False, "expected_payment": None,
        })
    return output


def build_report(packet, *, capture_sha256, order_cap=D(10), wallet_cap=D(100), cleanup_reserve=D(10), require_http=True):
    for value, name in ((order_cap, "order_cap"), (wallet_cap, "wallet_cap"), (cleanup_reserve, "cleanup_reserve")):
        number(value, name)
    if not isinstance(capture_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", capture_sha256):
        raise ValueError("capture:hash_invalid")
    validated = validate_packet(packet, require_http=require_http)
    qualifiers = _source_qualifiers(validated["rules"])
    rows = []
    with localcontext() as context:
        context.prec = 80
        for row in validated["rows"]:
            selection, reward = row["selection"], row["rewards"]
            blockers = [name + ":source_unqualified" for name, qualified in qualifiers.items() if not qualified]
            blockers.extend(("midpoint:size_cutoff_method_and_value_unqualified",
                             "campaign:timezone_boundary_and_epoch_unqualified",
                             "competition:per_maker_denominator_unobserved",
                             "cash:paid_rewards_and_all_in_pnl_unobserved"))
            plans = []
            if all(qualifiers.values()):
                try:
                    plans = _diagnostic_plans(row, validated["rules"], validated["as_of"],
                                              order_cap=order_cap, wallet_cap=wallet_cap, cleanup=cleanup_reserve)
                except (ValueError, FeasibilityInputError) as exc:
                    blockers.append("order_capital_diagnostic:" + str(exc))
            allocations = reward["rewards_config"] if reward else []
            positive = any(number(item["rate_per_day"], "rate") > 0 for item in allocations)
            same_asset = bool(allocations) and all(
                item["asset_address"].lower() == PUSD_COLLATERAL_PROXY_ADDRESS.lower()
                for item in allocations if number(item["rate_per_day"], "rate") > 0
            )
            if positive and not same_asset:
                blockers.append("cash:reward_collateral_conversion_unqualified")
            if not positive:
                blockers.insert(0, "campaign:no_positive_configured_allocation")
            rows.append({
                "location_id": selection["location_id"], "settlement_unit": spec_for_slug(selection["event_slug"]).unit,
                "event_slug": selection["event_slug"], "condition_id": selection["condition_id"],
                "question": row["market"].get("question"), "token_ids": row["tokens"],
                "status": "EVIDENCE_BLOCKED", "blockers": blockers,
                "observed_at_utc": validated["as_of"], "books": row["books"],
                "configured_allocations": allocations, "reward_collateral_same_asset": same_asset,
                "reward_minimum_shares": reward.get("rewards_min_size") if reward else None,
                "reward_maximum_distance_cents": reward.get("rewards_max_spread") if reward else None,
                "clob_fee_parameters": row["clob_market"].get("fd"), "terms_evidence": row["terms_evidence"],
                "configured_rates_are_earnings": False, "adjusted_midpoint": None,
                "order_capital_diagnostics": plans, "loss_sensitivity": _loss_sensitivity(allocations),
                "paid_rewards": None, "realized_pnl": None,
            })
    return json_value({
        "schema_version": schema_version("maker_opportunity_report"), "platform": "polymarket_global",
        "status": "EVIDENCE_BLOCKED", "mode": "public_capture_order_capital_diagnostic",
        "capture_sha256": capture_sha256, "selection_sha256": packet["selection_sha256"],
        "selection_policy_id": packet["selection"]["policy_id"], "as_of": validated["as_of"],
        "synthetic_inputs": validated["synthetic"], "source_qualifiers": qualifiers,
        "planning_assumptions": {"order_cap": order_cap, "backed_wallet_cap": wallet_cap, "cleanup_reserve": cleanup_reserve,
                                 "existing_inventory_and_own_orders": "assumed absent, not account evidence",
                                 "quote_policy": "one minimum-size BUY at each captured best bid, individually and together",
                                 "book_max_age_seconds": 120, "book_max_skew_seconds": 15},
        "rows": rows, "primary_opportunity": None, "reserve_opportunity": None,
        "paid_rewards": None, "realized_pnl": None, "live_order_authority": False,
        "next_evidence": "Qualify the venue's size-cutoff-adjusted midpoint and campaign/epoch boundaries before interpreting scoring or earning-duration scenarios. Anonymous depth is not a per-maker denominator.",
    })


def render_markdown(report):
    lines = [
        "# Maker opportunity evidence report", "",
        "**Verdict: " + report["status"] + ".** No profitable opportunity or live authority is established.", "",
        "Captured as of " + report["as_of"] + ". Capture SHA-256: `" + report["capture_sha256"] + "`.", "",
        "| Market | Reward minimum shares | Order/capital-feasible bid plans | Reward qualification |",
        "| --- | ---: | --- | --- |",
    ]
    for row in report["rows"]:
        feasible = [plan["label"] for plan in row["order_capital_diagnostics"] if plan["order_feasible"] and plan["capital_feasible"]]
        lines.append("| " + row["location_id"] + " | " + str(row["reward_minimum_shares"]) + " | " + (", ".join(feasible) or "None established") + " | Blocked |")
    lines.extend(("", "The bid plans assume the declared backed capital and no existing inventory or own orders. They do not establish reward eligibility. Configured allocations are neither earned rewards nor receivables.", "", report["next_evidence"], "",
                  "Reward assets remain separate from order collateral. Different token contracts require qualified conversion evidence before rewards and trading costs can share a P&L unit.", "",
                  "The JSON retains exact book references, order/capital blockers and loss sensitivity. Its hypothetical whole-epoch pools do not prorate configured daily rates, establish a payout threshold in fiat, or estimate payment.", ""))
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--capture-sha256", required=True)
    parser.add_argument("--output", type=Path, default=data_path("backtest", "maker_opportunity_report.json"))
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--order-cap", default="10")
    parser.add_argument("--wallet-cap", default="100")
    parser.add_argument("--cleanup-reserve", default="10")
    args = parser.parse_args(argv)
    if args.output.exists() or (args.markdown and args.markdown.exists()):
        parser.error("output already exists; use new report paths")
    packet, digest = read_json(args.capture)
    if digest != args.capture_sha256:
        parser.error("capture differs from reviewed SHA-256")
    report = build_report(packet, capture_sha256=digest, order_cap=number(args.order_cap, "order_cap"),
                          wallet_cap=number(args.wallet_cap, "wallet_cap"), cleanup_reserve=number(args.cleanup_reserve, "cleanup"))
    report["producer"] = {"module_file": str(Path(__file__).resolve()), "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    write_new_json(args.output, report)
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        with args.markdown.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(render_markdown(report))
    print(json.dumps({"status": report["status"], "rows": len(report["rows"]), "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
