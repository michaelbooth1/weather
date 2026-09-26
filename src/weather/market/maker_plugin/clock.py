"""Replayable station clocks and conservative observation-trigger vetoes."""
from datetime import timedelta
import math

from maker_core.contracts import InfoEvent, utc_time
from weather.market.maker_plugin.inputs import event_identity, records, timestamp
from weather.market.maker_plugin.nbp import CYCLES, parse
from weather.units import round_half_up

# Vendored from observation_clock.py, origin/codex/observation-clock-20260923
# d059cc78. Modal report minutes, NOT a guarantee of availability (SPECI exists).
STATION_ROUTINE_MINUTES = {
    "KATL": (52,), "KAUS": (53,), "KORD": (51,), "KDAL": (53,),
    "KBKF": (58,), "KHOU": (53,), "KLAX": (53,), "KMIA": (53,),
    "KLGA": (51,), "KSFO": (56,), "KSEA": (53,), "CYYZ": (0,),
}


class WeatherInformationClock:
    def __init__(self, universe, *, triggers=(), bulletins=()):
        self.universe = universe
        self.triggers = records(triggers)
        self.bulletins = records(bulletins)

    def upcoming(self, markets, from_utc, to_utc):
        utc_time(from_utc)
        utc_time(to_utc)
        if not timedelta(0) <= to_utc - from_utc <= timedelta(days=3):
            raise ValueError("clock_window_must_be_zero_to_three_days")
        events = []
        cursor = from_utc.replace(minute=0, second=0, microsecond=0) - timedelta(hours=4)
        while cursor <= to_utc:
            for market in markets:
                spec, _ = event_identity(market.event_id)
                schedule = [(cursor + timedelta(minutes=m), "scheduled_print", "pull")
                            for m in STATION_ROUTINE_MINUTES[spec.icao]]
                if cursor.hour in CYCLES:
                    schedule.append((cursor, "model_cycle", "widen"))
                if cursor.hour in (0, 6, 12, 18):
                    schedule.append((cursor + timedelta(minutes=210), "model_cycle", "widen"))
                for when, kind, hint in schedule:
                    if from_utc <= when <= to_utc and when < market.close_at_utc:
                        events.append(InfoEvent(kind, when, None, None, (market.condition_id,), 1., None, hint))
            cursor += timedelta(hours=1)
        return tuple(sorted(events, key=lambda e: (e.scheduled_at_utc, e.kind, e.affects)))

    def observe(self, markets, as_of_utc):
        utc_time(as_of_utc)
        events = []
        for market in markets:
            spec, target = event_identity(market.event_id)
            for raw in self.bulletins:
                if raw.get("station_id") != spec.icao or raw.get("target_date") != target.isoformat():
                    continue
                fetched = timestamp(raw["fetched_at"])
                if fetched > as_of_utc:
                    continue
                try:
                    issue, _, _ = parse(raw, spec.icao, target)
                except ValueError:
                    continue
                events.append(InfoEvent("model_cycle", issue, issue, fetched,
                                        (market.condition_id,), 1., None, "widen"))
            for row in self.triggers:
                if row.get("event_slug") != market.event_id:
                    continue
                detected = timestamp(row["current_captured_at_utc"])
                observed = timestamp(row["observed_at"]) if row.get("observed_at") else None
                if detected > as_of_utc or (observed and observed > detected):
                    continue
                if detected.astimezone(spec.tz).date() != target or (
                        observed and observed.astimezone(spec.tz).date() != target):
                    continue
                if row.get("market_id") != spec.id or row.get("unit") != spec.unit:
                    continue
                if row.get("target_date") != target.isoformat():
                    continue
                previous, current = row.get("previous_value"), row.get("current_value")
                if current is None or not math.isfinite(float(current)):
                    continue
                if previous is not None and float(current) <= float(previous):
                    continue
                # Supporting observations may cause a pull but never a hard
                # settlement floor. Only the captured WU printed high decides.
                if row.get("reason") != "wu_history_high_increased" or row.get("source") != "wu_history":
                    continue
                events.append(InfoEvent("new_high", None, observed, detected,
                                        (market.condition_id,), 1., None, "pull"))
                lo, hi = self.universe.bands(market.event_id, detected)[market.condition_id]
                bucket = row.get("current_bucket")
                if bucket is None or bucket != round_half_up(float(current)):
                    continue
                if float(bucket) > hi or (hi == math.inf and float(bucket) >= lo):
                    # decided maps to probability already determined, NOT p_yes.
                    events.append(InfoEvent("decided", None, observed, detected,
                        (market.condition_id,), 1., {market.condition_id: 1.}, "pull"))
        return tuple(sorted(events_without_mapping(events), key=lambda e:
                     (e.detected_at_utc, e.kind, e.affects)))


def events_without_mapping(events):
    """Deduplicate records without hashing MappingProxyType fields."""
    found = {}
    for event in events:
        key = (event.kind, event.scheduled_at_utc, event.observed_at_utc,
               event.detected_at_utc, event.affects)
        found[key] = event
    return tuple(found.values())
