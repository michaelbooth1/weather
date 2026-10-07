"""Shadow campaign book: a paper ledger the guard evaluates in shadow mode.

The paper account starts with declared cash. Its only trades are the runner's
own simulated fills of its hypothetical resting legs, taken from public prints
under a desk-study fill rule; maker fee 0. The guard book is produced by the
real portfolio ledger (``maker_core.portfolio.ledger.build_book``) from a paper
snapshot, so bleed is the ledger's P&L on paper (cash plus open lots marked at
the last two-sided mid read for the asset). No wallet, reader or venue account
is involved, and the paper account id can never equal a wallet address.
Contract: docs/operations/maker-shadow-runner.md.
"""
from datetime import datetime, timezone
from decimal import Decimal

from maker_core.contracts import utc_time
from maker_core.contracts.portfolio import CAMPAIGNS_SCHEMA, SNAPSHOT_SCHEMA, amount
from maker_core.portfolio.ledger import build_book

PAPER_ACCOUNT = "shadow-paper"
PAPER_CAMPAIGN = "shadow-maker"
PAPER_SLUG_PREFIX = "shadow-paper:"
FILL_RULES = ("strictly_through", "at_price")
D = Decimal


def crosses(rule, print_price, bid):
    """A print fills a resting BUY at ``bid``: strictly below it, or at or below it."""
    if rule not in FILL_RULES:
        raise ValueError("unknown_fill_rule")
    return print_price < bid if rule == "strictly_through" else print_price <= bid


def fill_legs(legs, prints, rule):
    """Fills of each leg (re-placed at full size per window) from time-ordered prints of its asset.

    ``legs``: (outcome, asset_id, price, size); ``prints``: (at, asset_id, price, size, key).
    Returns (outcome, asset_id, leg price, at, quantity, key) rows.
    """
    fills = []
    for outcome, asset, price, size in legs:
        remaining = size
        for at, print_asset, print_price, print_size, key in sorted(prints, key=lambda p: (p[0], p[4])):
            if remaining <= 0:
                break
            if print_asset == asset and crosses(rule, print_price, price):
                quantity = min(print_size, remaining)
                remaining -= quantity
                fills.append((outcome, asset, price, at, quantity, key))
    return fills


def paper_campaigns(*, starting_cash, bleed_limit, start_utc):
    utc_time(start_utc)
    start = start_utc.isoformat()
    return {"schema_version": CAMPAIGNS_SCHEMA, "account_id": PAPER_ACCOUNT,
            "default_campaign": "owner-discretionary", "unattributed_cash_pusd": "0",
            "campaigns": [{"id": PAPER_CAMPAIGN, "start_utc": start, "bleed_limit_pusd": str(bleed_limit),
                           "contributions": [{"id": "shadow-paper-start", "at_utc": start,
                                              "amount_pusd": str(starting_cash)}]},
                          {"id": "owner-discretionary", "start_utc": start, "contributions": []}],
            "lot_overrides": [], "rules": [{"campaign": PAPER_CAMPAIGN, "event_slug_prefix": PAPER_SLUG_PREFIX}]}


class PaperLedger:
    def __init__(self, *, starting_cash, bleed_limit, start_utc, fill_rule):
        self.starting_cash, self.bleed_limit = amount(starting_cash), amount(bleed_limit)
        if self.starting_cash <= 0 or self.bleed_limit < 0 or fill_rule not in FILL_RULES:
            raise ValueError("invalid_paper_book")
        self.start, self.fill_rule = start_utc, fill_rule
        self.campaigns = paper_campaigns(starting_cash=self.starting_cash, bleed_limit=self.bleed_limit,
                                         start_utc=start_utc)
        self.trades, self.marks, self.conditions, self.seen = [], {}, {}, set()

    def mark(self, asset_id, condition_id, bids, asks, at_utc):
        """Remember the latest two-sided top of book of an asset (one-sided books are not marks)."""
        self.conditions[asset_id] = condition_id
        if bids and asks:
            self.marks[asset_id] = (max(p for p, _ in bids), min(p for p, _ in asks), at_utc)

    def cash(self):
        return self.starting_cash - sum((amount(t["size"]) * amount(t["price"]) for t in self.trades), D(0))

    def fill(self, *, condition_id, event_id, asset_id, price, size, at_utc, key):
        """Record one simulated BUY fill; identical prints count once; same-instant fills of an asset merge."""
        if key in self.seen:
            return None
        self.seen.add(key)
        self.conditions[asset_id] = condition_id
        at = at_utc.isoformat()
        last = self.trades[-1] if self.trades else None
        if last and last["asset_id"] == asset_id and last["at_utc"] == at and amount(last["price"]) == price:
            last["size"] = str(amount(last["size"]) + size)
            return last
        trade = {"event_id": f"paper-{len(self.trades)}", "transaction_hash": f"paper-{len(self.trades)}",
                 "asset_id": asset_id, "condition_id": condition_id, "event_slug": PAPER_SLUG_PREFIX + event_id,
                 "at_utc": at, "side": "BUY", "size": str(size), "price": str(price), "fee_pusd": "0"}
        self.trades.append(trade)
        return trade

    def snapshot(self, now_utc):
        held = {}
        for t in self.trades:
            held[t["asset_id"]] = held.get(t["asset_id"], D(0)) + amount(t["size"])
        positions = []
        for asset, size in sorted(held.items()):
            bid, ask, _ = self.marks.get(asset, (None, None, None))
            positions.append({"asset_id": asset, "condition_id": self.conditions[asset], "event_slug": "",
                              "size": str(size), "avg_price": "0", "classification": "live",
                              "bid": None if bid is None else str(bid), "ask": None if ask is None else str(ask),
                              "terminal_price": None, "redeemable": False})
        return {"schema_version": SNAPSHOT_SCHEMA, "account_id": PAPER_ACCOUNT, "as_of_utc": now_utc.isoformat(),
                "cash_pusd": str(self.cash()), "positions": positions, "trades": [dict(t) for t in self.trades],
                "positions_complete": True, "history_complete": True, "history_start_utc": self.start.isoformat()}

    def book(self, now_utc):
        return build_book([self.snapshot(now_utc)], self.campaigns)

    def summary(self, book, now_utc):
        entry = book["campaigns"].get(PAPER_CAMPAIGN, {})
        ages = [(now_utc - at).total_seconds() for asset, (_, _, at) in self.marks.items()
                if any(t["asset_id"] == asset for t in self.trades)]
        return {"cash_pusd": str(self.cash()), "trade_count": len(self.trades), "status": book["status"],
                "pnl_pusd": entry.get("pnl_pusd"), "bleed_limit_pusd": str(self.bleed_limit),
                "bleed_limit_reached": entry.get("bleed_limit_reached"),
                "held_mark_max_age_seconds": max(ages) if ages else None}


def parse_prints(rows, condition_id):
    """Public trade rows (data-api ``/trades``) -> (at, asset, price, size, key); other conditions dropped."""
    prints = []
    for row in rows:
        if str(row.get("conditionId", "")).lower() != condition_id:
            continue
        at = datetime.fromtimestamp(int(row["timestamp"]), tz=timezone.utc)
        price, size = D(str(row["price"])), D(str(row["size"]))
        key = "|".join(str(x) for x in (row.get("transactionHash"), row.get("asset"), price, size, row["timestamp"]))
        prints.append((at, str(row["asset"]), price, size, key))
    return prints


__all__ = ["FILL_RULES", "PAPER_ACCOUNT", "PAPER_CAMPAIGN", "PaperLedger", "crosses", "fill_legs",
           "paper_campaigns", "parse_prints"]
