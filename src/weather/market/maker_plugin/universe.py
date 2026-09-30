"""Local T+0..T+2 universe from 88a discovery/books plus snapshot band metadata.

88a selection_projection omits band boundaries, tick and minimum order size.
Those must be supplied from captured long rows and both-token books, never
inferred from rewardsMinSize (a different contract) or fetched here.
"""
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
import json

from maker_core.contracts import MarketDescriptor, UniverseSnapshot, utc_time
from weather.market.maker_plugin import PLUGIN_VERSION
from weather.market.maker_plugin.inputs import band, body, digest, event_identity, latest, records, timestamp


class WeatherUniverse:
    """``identity_band_rows`` hold one event's complete CLOB token batch.

    A condition's band is part of its immutable question, so a batch captured
    after the decision minute still describes the same contract. It is used
    only when no band capture exists at or before the minute, and only after
    ``identity_matches`` confirms that the point-in-time discovery lists
    exactly the batch's conditions with the same YES/NO tokens. It never
    supplies partition membership, prices or any other time-varying input.
    """
    def __init__(self, *, discovery=(), books=(), band_rows=(), identity_band_rows=()):
        self.discovery = records(discovery)
        self.books = records(books)
        self.band_rows = records(band_rows)
        self.identity_band_rows = records(identity_band_rows)

    def _captured(self, event_slug, as_of):
        return [r for r in self.band_rows if r["event_slug"] == event_slug
                and timestamp(r["captured_at_utc"]) <= as_of]

    def band_basis(self, event_slug, as_of):
        if self._captured(event_slug, as_of):
            return "point_in_time_capture"
        if any(r["event_slug"] == event_slug for r in self.identity_band_rows):
            return "condition_identity"
        return None

    def bands(self, event_slug, as_of):
        candidates = self._captured(event_slug, as_of)
        if not candidates:
            candidates = [r for r in self.identity_band_rows if r["event_slug"] == event_slug]
        if not candidates:
            raise ValueError("missing_captured_band_metadata")
        when = max(timestamp(r["captured_at_utc"]) for r in candidates)
        selected = [r for r in candidates if timestamp(r["captured_at_utc"]) == when]
        result = {}
        for row in selected:
            identity = row["condition_id"].lower()
            if identity in result:
                raise ValueError("duplicate_band_identity")
            result[identity] = band(row)
        return result

    def identity_matches(self, event):
        """Point-in-time discovery lists exactly the identity batch's contracts."""
        rows = {r["condition_id"].lower(): r["tokens"] for r in self.identity_band_rows
                if r["event_slug"] == event["slug"]}
        listed = {}
        for row in event["markets"]:
            outcomes, tokens = row.get("outcomes"), row.get("clobTokenIds")
            outcomes = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
            tokens = json.loads(tokens) if isinstance(tokens, str) else tokens
            if (not isinstance(outcomes, list) or not isinstance(tokens, list) or len(tokens) != 2
                    or len(outcomes) != 2 or set(outcomes) != {"Yes", "No"}):
                return False
            listed[str(row["conditionId"]).lower()] = {name.upper(): str(tokens[outcomes.index(name)])
                                                       for name in outcomes}
        return bool(rows) and rows == listed

    def _events(self, as_of):
        events = {}
        for captured in self.discovery:
            if timestamp(captured["captured_at_utc"]) > as_of or not captured.get("body_stored"):
                continue
            for event in body(captured):
                events.setdefault(event["slug"], []).append({
                    "captured_at_utc": captured["captured_at_utc"], "event": event})
        return [latest(rows, as_of) for _, rows in sorted(events.items())]

    def _book(self, token, as_of):
        found = []
        for capture in self.books:
            if timestamp(capture["captured_at_utc"]) > as_of or not capture.get("body_stored"):
                continue
            for book in body(capture):
                if str(book["asset_id"]) == token:
                    found.append({"captured_at_utc": capture["captured_at_utc"], "book": book})
        if not found:
            # 88a books only its selected, reward-eligible bands: a coverage
            # limit of the capture, distinct from a missing clock or metadata.
            raise ValueError("book_not_captured")
        return latest(found, as_of)["book"]

    def discover(self, as_of_utc, horizon_days):
        utc_time(as_of_utc)
        if isinstance(horizon_days, bool) or horizon_days not in (0, 1, 2):
            raise ValueError("supported_horizon_is_zero_to_two")
        markets = []
        for captured in self._events(as_of_utc):
            event = captured["event"]
            spec, target = event_identity(event["slug"])
            lead = (target - as_of_utc.astimezone(spec.tz).date()).days
            if not 0 <= lead <= horizon_days:
                continue
            bands = self.bands(event["slug"], as_of_utc)
            for row in event["markets"]:
                if row.get("closed") or not row.get("active") or row.get("enableOrderBook") is False:
                    continue
                cid = row["conditionId"].lower()
                outcomes, tokens = row["outcomes"], row["clobTokenIds"]
                outcomes = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
                tokens = json.loads(tokens) if isinstance(tokens, str) else tokens
                if len(tokens) != 2 or len(outcomes) != 2 or set(outcomes) != {"Yes", "No"}:
                    raise ValueError("invalid_outcome_mapping")
                pair = {name.upper(): str(tokens[outcomes.index(name)]) for name in outcomes}
                books = [self._book(token, as_of_utc) for token in pair.values()]
                if any(b["market"].lower() != cid for b in books) or cid not in bands:
                    raise ValueError("captured_condition_mismatch")
                if self.band_basis(event["slug"], as_of_utc) == "condition_identity" and pair not in (
                        r["tokens"] for r in self.identity_band_rows
                        if r["event_slug"] == event["slug"] and r["condition_id"].lower() == cid):
                    raise ValueError("band_identity_mismatch")
                terms = {(Decimal(str(b["tick_size"])), Decimal(str(b["min_order_size"]))) for b in books}
                if len(terms) != 1:
                    raise ValueError("ambiguous_book_rules")
                tick, size = terms.pop()
                close = datetime.combine(target + timedelta(days=1), time(), spec.tz).astimezone(timezone.utc)
                markets.append(MarketDescriptor(
                    "weather", event["slug"], cid, pair, tick, size, event["slug"], close, None,
                    spec.unit, PLUGIN_VERSION, {"discovery": digest(captured),
                    "band": digest([str(v) for v in bands[cid]]),
                    "band_basis": self.band_basis(event["slug"], as_of_utc),
                    "book_rules": digest([str(tick), str(size)])}, group_relation="partition"))
        ordered = tuple(sorted(markets, key=lambda m: m.condition_id))
        return UniverseSnapshot(ordered, as_of_utc, {"descriptors": digest([
            [m.condition_id, dict(m.source_hashes)] for m in ordered])})

    def describe(self, condition_id, as_of_utc):
        for market in self.discover(as_of_utc, 2).markets:
            if market.condition_id == condition_id:
                return market
        raise KeyError(condition_id)
