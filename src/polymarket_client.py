import json

import requests

from market_config import config_for_date, config_from_event


DEFAULT_MARKET_CONFIG = config_for_date()
TORONTO_EVENT_SLUG = DEFAULT_MARKET_CONFIG.event_slug
TORONTO_POLYMARKET_URL = DEFAULT_MARKET_CONFIG.polymarket_url
GAMMA_EVENT_URL = f"https://gamma-api.polymarket.com/events/slug/{TORONTO_EVENT_SLUG}"


class PolymarketClient:
    def __init__(self, timeout=10, target_date=None):
        self.timeout = timeout
        self.config = config_for_date(target_date)

    def get_toronto_weather_event(self):
        response = requests.get(self.gamma_event_url, timeout=self.timeout)
        response.raise_for_status()
        event = response.json()
        self.config = config_from_event(event, fallback_date=self.config.target_date)
        return event

    @property
    def event_slug(self):
        return self.config.event_slug

    @property
    def polymarket_url(self):
        return self.config.polymarket_url

    @property
    def gamma_event_url(self):
        return f"https://gamma-api.polymarket.com/events/slug/{self.config.event_slug}"

    def event_market_rows(self, event):
        markets = event.get("markets", []) or []
        rows = [self._market_row(market) for market in markets]
        return sorted(rows, key=self._sort_key)

    def _market_row(self, market):
        outcomes, prices = self._parse_json_list(market.get("outcomes")), self._parse_json_list(
            market.get("outcomePrices")
        )

        yes_price = self._price_for_outcome("Yes", outcomes, prices)
        no_price = self._price_for_outcome("No", outcomes, prices)

        return {
            "Range": market.get("groupItemTitle") or market.get("question", ""),
            "Yes": self._format_price(yes_price),
            "No": self._format_price(no_price),
            "Best bid": self._format_price(market.get("bestBid")),
            "Best ask": self._format_price(market.get("bestAsk")),
            "Last": self._format_price(market.get("lastTradePrice")),
            "Volume": self._format_dollars(market.get("volumeNum") or market.get("volume")),
            "Liquidity": self._format_dollars(
                market.get("liquidityNum") or market.get("liquidity")
            ),
            "Status": self._status(market),
        }

    def _parse_json_list(self, value):
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, list) else []
            except json.JSONDecodeError:
                return []
        return []

    def _price_for_outcome(self, name, outcomes, prices):
        for index, outcome in enumerate(outcomes):
            if str(outcome).lower() == name.lower() and index < len(prices):
                return prices[index]
        return None

    def _format_price(self, value):
        if value is None or value == "":
            return "-"
        try:
            return f"{float(value) * 100:.1f}%"
        except (TypeError, ValueError):
            return str(value)

    def _format_dollars(self, value):
        if value is None or value == "":
            return "-"
        try:
            return f"${float(value):,.0f}"
        except (TypeError, ValueError):
            return str(value)

    def _status(self, market):
        if market.get("closed"):
            return market.get("umaResolutionStatus") or "closed"
        if market.get("active"):
            return "active"
        return "inactive"

    def _sort_key(self, row):
        label = row.get("Range", "")
        digits = "".join(ch for ch in label if ch.isdigit())
        if "below" in label.lower():
            return -1
        if "higher" in label.lower():
            return 10_000
        return int(digits) if digits else 9_999
