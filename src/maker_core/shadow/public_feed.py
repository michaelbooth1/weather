"""Strict public response projection; raw HTTP fields never enter the journal."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json

from maker_core.evidence.journal import digest, plain
from maker_core.replay.bundle import CapturedRecord
from maker_core.replay.payloads import decode


class Feed:
    def __init__(self, descriptors):
        self.markets = {m.condition_id: m for m in descriptors}
        self.assets = {asset: (m.condition_id, outcome) for m in descriptors
                       for outcome, asset in m.outcome_tokens.items()}
        if len(self.assets) != 2 * len(self.markets):
            raise ValueError("public_asset_collision")
        self.sequence, self.last_health = -1, None

    def record(self, cid, kind, at, payload, source):
        self.sequence += 1
        payload = plain(payload)
        row = CapturedRecord(self.sequence, at, cid, kind, payload, digest(payload), {"public": digest(source)})
        decode(row)
        return row

    def books(self, cid, at, yes, no):
        market = self.markets[cid]
        for outcome, body in (("YES", yes), ("NO", no)):
            if body["market"] != cid or str(body["asset_id"]) != market.outcome_tokens[outcome]:
                raise ValueError("public_book_identity")
            if (Decimal(str(body["tick_size"])) != market.tick
                    or Decimal(str(body["min_order_size"])) != market.min_order_size):
                raise ValueError("public_market_rules_changed")
        times = [datetime.fromtimestamp(int(b["timestamp"])/1000, timezone.utc) for b in (yes, no)]
        if any(t > at or at-t > timedelta(seconds=10) for t in times):
            raise ValueError("public_book_clock")
        payload = {"as_of_utc": min(times), "post_only_available": True}
        for prefix, body in (("yes", yes), ("no", no)):
            for side in ("bids", "asks"):
                payload[prefix+"_"+side] = [(v["price"], v["size"]) for v in body[side]]
        return self.record(cid, "book", at, payload, [yes, no])

    def terms(self, cid, at, body):
        matches = [r for r in body["data"] if r["condition_id"] == cid]
        if len(matches) != 1 or len(body["data"]) != 1:
            raise ValueError("public_terms_identity")
        row = matches[0]
        rates = [Decimal(str(r["rate_per_day"])) for r in row["rewards_config"]
                 if str(r["start_date"])[:10] <= at.date().isoformat() <= str(r["end_date"])[:10]]
        return self.record(cid, "terms", at, {"as_of_utc": at, "min_size": row["rewards_min_size"],
                           "max_spread_cents": row["rewards_max_spread"], "rate_per_day": sum(rates, Decimal(0))}, body)

    def stream(self, at, raw):
        if raw == "PONG":
            self.last_health = at
            return self.health(at)
        body = json.loads(raw)
        events = body if isinstance(body, list) else [body]
        if len(events) > 512:
            raise ValueError("public_stream_batch_cap")
        rows = []
        for event in events:
            kind = event["event_type"]
            if kind not in ("book", "price_change", "last_trade_price", "tick_size_change", "best_bid_ask"):
                raise ValueError("unreviewed_public_stream_event")
            if event["market"] not in self.markets:
                raise ValueError("unsubscribed_condition")
            if kind == "tick_size_change":
                raise ValueError("public_market_rules_changed")
            if kind == "last_trade_price":
                cid, outcome = self.assets[event["asset_id"]]
                if cid != event["market"]:
                    raise ValueError("public_trade_identity")
                # No venue trade id is promised by this channel. Bind the entire
                # print identity; indistinguishable collisions remain a public-data limitation.
                identity = {k: event[k] for k in ("market", "asset_id", "timestamp", "price", "size", "side")}
                rows.append(self.record(cid, "trade", at,
                    {"trade_id": digest(identity), "outcome": outcome, "price": event["price"],
                     "size": event["size"], "aggressor_side": event["side"],
                     "traded_at_utc": datetime.fromtimestamp(int(event["timestamp"])/1000, timezone.utc)}, event))
        self.last_health = at
        return rows + self.health(at)

    def health(self, at):
        return [self.record(cid, "coverage", at,
                {"trade_stream_ok": True, "valid_until_utc": at + timedelta(seconds=15)},
                {"received_at": at, "scope": sorted(self.assets)}) for cid in sorted(self.markets)]
