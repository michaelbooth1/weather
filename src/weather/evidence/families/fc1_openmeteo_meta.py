"""FC-1 Open-Meteo run-identity sampler: ``/data/<model>/static/meta.json`` per single model.

Change-only rows keyed by model: a new row appears when the provider publishes a new run
(``last_run_initialisation_time``) or changes its availability stamps. ``run_init`` is assigned
only here, from a single-model meta reply; blended products are not sampled. Shadow calls run
outside the channel's ``quiet_local`` window (12:00-18:00) and stop at a hard per-UTC-day meter,
long before the free tier's limit; a 429 writes a ``cap`` row and stops the poll.
"""
from __future__ import annotations

from weather.evidence.envelope import epoch_utc_text
from weather.evidence.families.common import item, json_body

PARSER_VERSION = "fc1-meta-1"
DEFAULT_BASE_URL = "https://api.open-meteo.com/data"
META_FIELDS = ("last_run_initialisation_time", "last_run_modification_time", "last_run_availability_time",
               "update_interval_seconds", "temporal_resolution_seconds", "data_end_time", "crs_wkt")


def meta_item(model, payload) -> dict:
    payload = payload if isinstance(payload, dict) else {}
    body = {"model": model, **{k: payload.get(k) for k in META_FIELDS if k != "crs_wkt"}}
    return item(model, body, parser_version=PARSER_VERSION,
                provider_time=epoch_utc_text(payload.get("last_run_availability_time")),
                run_init=epoch_utc_text(payload.get("last_run_initialisation_time")))


class DailyMeter:
    """Hard per-UTC-day call meter held in the channel state."""

    def __init__(self, state, limit):
        self.state, self.limit = state, int(limit)

    def take(self, day) -> bool:
        if self.state.get("meter_day") != day:
            self.state["meter_day"], self.state["meter_calls"], self.state["meter_capped"] = day, 0, False
        if self.state["meter_calls"] >= self.limit:
            return False
        self.state["meter_calls"] += 1
        return True


def build(cfg, locations):
    from weather.evidence.child import Channel
    spec = cfg["channels"]["run_meta"]
    base = spec.get("base_url", DEFAULT_BASE_URL)
    models = list(spec["models"])

    def poll(ctx):
        meter = DailyMeter(ctx.state, spec["daily_call_meter"])
        day = ctx.now().date().isoformat()
        items = []
        for model in models:
            if not meter.take(day):
                if not ctx.state.get("meter_capped"):
                    ctx.state["meter_capped"] = True
                    ctx.journal.event("cap", {"reason": "daily_call_meter", "limit": meter.limit},
                                      channel=ctx.channel)
                break
            response = ctx.fetch(f"{base}/{model}/static/meta.json")
            if response.status == 429:
                ctx.journal.event("cap", {"reason": "provider_429", "model": model}, channel=ctx.channel)
                break
            if response.status != 200:
                ctx.gap("http_status", status=response.status, model=model)
                continue
            items.append(meta_item(model, json_body(response)))
        ctx.record(items, meta={"models": len(models), "meter_calls": ctx.state.get("meter_calls")})

    if not spec.get("enabled", True):
        return []
    return [Channel("run_meta", float(spec["interval_seconds"]), poll, optional=bool(spec.get("optional", True)),
                    quiet_local=tuple(tuple(w) for w in spec.get("quiet_local", [])))]
