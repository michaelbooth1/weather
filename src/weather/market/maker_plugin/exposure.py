"""Weather region factors, using the canonical pure mm_risk group table."""
from weather.market.mm_risk import DEFAULT_CORRELATED_MARKET_GROUPS
from weather.market.maker_plugin.inputs import event_identity


class WeatherExposure:
    def factors(self, market):
        spec, _ = event_identity(market.event_id)
        return {"weather:" + DEFAULT_CORRELATED_MARKET_GROUPS[spec.id]: 1.}
