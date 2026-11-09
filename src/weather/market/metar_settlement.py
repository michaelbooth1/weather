"""Global settlement library and public GET-only diagnostic CLI. No service or order access."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Iterable
from zoneinfo import ZoneInfo

from weather.market.metar_reports import MetarReport, aware_utc, routine_revision_conflicts
from weather.market.venue_settlement_rules import select_reports, settlement_bucket
from weather.market.weather_universe import BinInterval, WeatherCitySpec, load_weather_universe, parse_bin_label

UTC = timezone.utc


@dataclass(frozen=True)
class DailySettlement:
    city: str
    local_date: date
    status: str
    maximum_c: Decimal | None = None
    minimum_c: Decimal | None = None
    maximum: Decimal | int | None = None
    minimum: Decimal | int | None = None
    maximum_observation: MetarReport | None = None
    minimum_observation: MetarReport | None = None
    observation_count: int = 0
    cutoff: datetime | None = None
    source: str = "metar_routine"
    notes: tuple[str, ...] = ()
    fallback_deadline: datetime | None = None
    family_statuses: dict[str, str] | None = None
    source_read_at: datetime | None = None

    def status_for(self, family: str) -> str:
        return (self.family_statuses or {}).get(family, self.status)

    def condition_for(self, family: str):
        status = self.status_for(family)
        if self.source == "hko_daily_extract":
            condition = (self.source_read_at if status in {"final", "initial_publication_unverified"}
                         and self.source_read_at is not None else self.fallback_deadline or self.cutoff)
            return condition, ("hko_publication_or_revision", "clearly_erroneous_print_correction")
        if status in {"wu_fallback", "lowest_bracket_fallback", "awaiting_wu_fallback"}:
            return self.fallback_deadline or self.cutoff, (
                "wu_publication_or_revision", "clearly_erroneous_print_correction")
        return self.cutoff, ("awc_cor_or_unmarked_replacement", "clearly_erroneous_print_correction")


@dataclass(frozen=True)
class BinPossibility:
    interval: BinInterval
    possible: bool
    bound: Decimal | int | None
    observation: MetarReport | None
    conditional_until: datetime | None
    witness_observation_time: datetime | None
    invalidating_events: tuple[str, ...] = ("awc_cor_or_unmarked_replacement", "clearly_erroneous_print_correction")


def possible_bins(result: DailySettlement, family: str, bins: Iterable[BinInterval]) -> tuple[BinPossibility, ...]:
    if family not in {"highest", "lowest"}:
        raise ValueError("invalid family")
    bound = result.maximum if family == "highest" else result.minimum
    observation = result.maximum_observation if family == "highest" else result.minimum_observation
    status = result.status_for(family)
    condition, events = result.condition_for(family)
    out = []
    bins = tuple(bins)
    first = min(bins, key=lambda b: b.lower if b.lower is not None else Decimal("-Infinity"), default=None)
    for interval in bins:
        possible = True
        if status == "lowest_bracket_fallback":
            possible = interval == first
        elif bound is not None and status != "initial_publication_unverified":
            if status in {"final", "wu_fallback"}:
                possible = interval.contains(bound)
            elif family == "highest" and interval.upper is not None:
                possible = bound < interval.upper or (bound == interval.upper and interval.upper_closed)
            elif family == "lowest" and interval.lower is not None:
                possible = bound > interval.lower or (bound == interval.lower and interval.lower_closed)
        out.append(BinPossibility(interval, possible, bound, observation, condition,
                                  observation.observation_time if observation else None, events))
    return tuple(out)


class MetarSettlementAdapter:
    def evaluate(self, spec: WeatherCitySpec, local_date: date, reports: Iterable[MetarReport], *,
                 as_of: datetime, wu_values: tuple[Decimal, Decimal] | None = None,
                 wu_empty: bool = False, wu_read_at: datetime | None = None,
                 family: str = "highest") -> DailySettlement:
        """Evaluate a captured source view as of t; WU values are (daily high, daily low), native unit.

        A raw snapshot without receipt times cannot prove the publication cutoff. It
        carries an explicit note. Receipt-bearing replay excludes late revisions.
        """
        as_of = aware_utc(as_of)
        if family not in {"highest", "lowest"}:
            raise ValueError("invalid family")
        if wu_read_at is not None:
            wu_read_at = aware_utc(wu_read_at)
        if not isinstance(wu_empty, bool):
            raise ValueError("wu_empty must be an explicit boolean")
        if wu_empty and wu_values is not None:
            raise ValueError("WU cannot be both empty and populated")
        zone = ZoneInfo(spec.timezone)
        tomorrow = local_date + timedelta(days=1)
        fallback_deadline = datetime.combine(tomorrow, time(23, 59), ZoneInfo("America/New_York")).astimezone(UTC)
        cutoff = fallback_deadline
        received = [r for r in reports if r.receipt_time is None or r.receipt_time <= as_of]
        station_reports = [r for r in received if r.station == spec.station_id]
        unassigned_defects = [r for r in station_reports if r.routine and r.observation_time is None and r.has_parse_defect]
        records = [r for r in station_reports if r.observation_time is not None and r.observation_time <= as_of]
        next_reports = [r for r in records if r.routine and r.observation_time.astimezone(zone).date() == tomorrow]
        if next_reports:
            cutoff = min(cutoff, min(r.receipt_time or r.observation_time for r in next_reports))
        unattributed_defects = [r for r in received if r.station is None and r.routine and r.has_parse_defect
                               and (r.observation_time is None or r.observation_time <= as_of
                                    and r.observation_time.astimezone(zone).date() == local_date)
                               and (r.receipt_time is None or r.receipt_time < cutoff)]
        routine_day = [r for r in records if r.routine and r.observation_time.astimezone(zone).date() == local_date]
        eligible = [r for r in routine_day if r.receipt_time is None or r.receipt_time < cutoff]
        rejected = len(routine_day) - len(eligible)
        notes = [f"rejected_late_revisions={rejected}"] if rejected else []
        if routine_revision_conflicts(eligible) or any("ambiguous_source_revision" in r.flags for r in eligible):
            return DailySettlement(spec.slug, local_date, "source_unavailable", cutoff=cutoff,
                                   fallback_deadline=fallback_deadline,
                                   notes=tuple(notes) + ("ambiguous_routine_revision",))
        routine = [dict(valid_time_utc=r.observation_time,
                        local_date=r.observation_time.astimezone(zone).date().isoformat(),
                        corrected=r.corrected, receipt_utc=r.receipt_time, raw=r.raw, report=r) for r in eligible]
        selected, _ = select_reports(routine, snapshot_order=True, deadlines={local_date.isoformat(): cutoff})
        selected_reports = [item["report"] for item in selected]
        parse_defects = [r for r in unassigned_defects if r.receipt_time is None or r.receipt_time < cutoff]
        parse_defects += unattributed_defects + [r for r in selected_reports if r.has_parse_defect]
        day_reports = [r for r in selected_reports if r.temperature_c is not None]
        if parse_defects:
            notes.append("routine_day_parse_defect")
        if any(r.receipt_time is None for r in records):
            notes.append("publication_cutoff_unverified_without_receipt_times")
        final = as_of >= cutoff
        if not day_reports:
            if parse_defects:
                return DailySettlement(spec.slug, local_date, "source_unavailable", cutoff=cutoff,
                                       notes=tuple(notes), fallback_deadline=fallback_deadline)
            if as_of >= fallback_deadline and wu_values is not None and (wu_read_at is None or wu_read_at <= as_of):
                high, low = map(Decimal, wu_values)
                if not (high.is_finite() and low.is_finite() and low <= high):
                    raise ValueError("invalid WU daily extrema")
                return DailySettlement(spec.slug, local_date, "wu_fallback", maximum=high, minimum=low,
                                       cutoff=fallback_deadline, source="wu_daily_history", notes=tuple(notes),
                                       fallback_deadline=fallback_deadline, source_read_at=wu_read_at)
            fresh_empty = wu_empty and wu_read_at is not None and fallback_deadline <= wu_read_at <= as_of
            if wu_empty and not fresh_empty:
                notes.append("wu_emptiness_not_read_after_deadline")
            status = ("lowest_bracket_fallback" if as_of >= fallback_deadline and fresh_empty else
                      "awaiting_wu_fallback" if final else "missing")
            return DailySettlement(spec.slug, local_date, status, cutoff=cutoff, notes=tuple(notes),
                                   fallback_deadline=fallback_deadline, source_read_at=wu_read_at,
                                   source="wu_daily_history" if status == "lowest_bracket_fallback" else "metar_routine")
        high = max(day_reports, key=lambda r: r.temperature_c)
        low = min(day_reports, key=lambda r: r.temperature_c)
        return DailySettlement(spec.slug, local_date, "parse_incomplete" if parse_defects else "final" if final else "running",
                               high.temperature_c, low.temperature_c,
                               settlement_bucket(high.temperature_c, spec.market_unit),
                               settlement_bucket(low.temperature_c, spec.market_unit), high, low,
                               len(day_reports), cutoff, notes=tuple(notes), fallback_deadline=fallback_deadline)


class WUDailyHistoryAdapter:
    def evaluate(self, spec, local_date, reports=(), *, as_of, **kwargs):
        return DailySettlement(spec.slug, local_date, "not_implemented", source="wu_daily_history",
                               notes=("WU reader intentionally unimplemented; no credentials or scraping",))


def adapter_for(spec: WeatherCitySpec):
    if spec.settlement_kind == "metar_routine":
        return MetarSettlementAdapter()
    if spec.settlement_kind == "wu_daily_history":
        return WUDailyHistoryAdapter()
    from weather.market.hko_settlement import HKODailyExtractAdapter
    return HKODailyExtractAdapter()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    now = sub.add_parser("now", help="Read-only running local-day extrema and today's public event bins")
    now.add_argument("--family", choices=("highest", "lowest"), required=True)
    now.add_argument("--cities", nargs="+", help="City slugs, separated by spaces or commas")
    args = parser.parse_args(argv)
    universe = load_weather_universe()
    names = [name for value in (args.cities or sorted(universe)) for name in value.split(",")]
    if any(name not in universe for name in names):
        parser.error("unknown city")
    specs = [universe[name] for name in dict.fromkeys(names)]
    from weather.market.settlement_public import PublicSettlementClient
    client = PublicSettlementClient()
    as_of = datetime.now(UTC)
    reports, diagnostics = client.metars([
        s.station_id for s in specs if s.settlement_kind == "metar_routine" and args.family in s.families
    ], as_of)
    errors = bool(diagnostics.get("errors"))
    for spec in specs:
        day = as_of.astimezone(ZoneInfo(spec.timezone)).date()
        if args.family not in spec.families:
            print(json.dumps(dict(city=spec.slug, local_date=day.isoformat(), status="family_unavailable")))
            continue
        adapter = adapter_for(spec)
        try:
            if spec.settlement_kind == "hko_daily_extract":
                payload = client.hko_payloads(day)
                result = adapter.evaluate(spec, day, reports, as_of=datetime.now(UTC),
                                          family=args.family, hko_payloads=payload)
            else:
                result = adapter.evaluate(spec, day, reports, as_of=as_of, family=args.family)
        except (ValueError, OSError) as exc:
            result = DailySettlement(spec.slug, day, "source_error", notes=(str(exc),))
            errors = True
        if spec.settlement_kind == "metar_routine" and diagnostics.get("errors"):
            result = replace(result, status="source_error" if result.status == "missing" else result.status,
                             notes=result.notes + ("incomplete_awc_fetch",))
        slug = spec.event_slug(args.family, day)
        try:
            labels = client.event_bins(slug)
            bins = [parse_bin_label(label, spec.market_unit, continuous=spec.settlement_kind == "hko_daily_extract")
                    for label in labels]
            possible = [item.interval.label for item in possible_bins(result, args.family, bins) if item.possible]
            event_status = "ok" if labels else "event_unavailable"
        except (ValueError, OSError) as exc:
            possible, event_status = [], f"event_error:{exc}"
            errors = True
        observation = result.maximum_observation if args.family == "highest" else result.minimum_observation
        value = result.maximum if args.family == "highest" else result.minimum
        condition, events = result.condition_for(args.family)
        print(json.dumps(dict(city=spec.slug, local_date=day.isoformat(), event_slug=slug,
                              status=result.status_for(args.family), unit=spec.market_unit,
                              running_value=None if value is None else str(value),
                              possible_bins=possible, event_status=event_status,
                              bound_observation=observation.raw if observation else None, notes=result.notes,
                              conditional_until=condition.isoformat() if condition else None,
                              witness_observation_time=observation.observation_time.isoformat() if observation else None,
                              invalidating_events=events)))
    print(json.dumps(diagnostics), file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
