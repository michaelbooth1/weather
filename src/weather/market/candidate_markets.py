"""Inactive candidate market registry for the new-city model lane (M1).

``config/candidate_markets.json`` holds candidate ``MarketSpec`` rows for cities
that are being built on the workstation but are not served, captured or
scheduled. It is deliberately a separate file:

* The default market registry (``market_registry.build_registry``) is the
  built-ins plus ``config/markets.json``. This file is never that default, so
  ``all_specs()`` in every production loop, supervisor, serving and release
  path is unchanged by a row added here.
* The file uses the external-registry schema, so a workstation training or
  corpus process can opt in explicitly with
  ``WEATHER_MARKET_REGISTRY=config/candidate_markets.json``. International live
  paths refuse that override (``weather.operations.live_path_security``).
* Each row also carries the label contract the built-in specs do not have:
  the METAR (IEM) label source and the METAR print-cutoff rule.

Only workstation research modules import this module. A test holds that no
production entry point reaches it.

CLI:
  python -m weather.market.candidate_markets check
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from weather.market.market_registry import (
    BUILTIN_SPECS,
    MARKET_REGISTRY_SCHEMA_VERSION,
    MarketSpec,
    market_spec_from_mapping,
)
from weather.paths import config_path


CANDIDATE_REGISTRY_PATH = config_path("candidate_markets.json")
CANDIDATE_REGISTRY_STATUS = "candidate_registry_inactive"
CANDIDATE_LIFECYCLE = "candidate"
CANDIDATE_ROW_FIELDS = frozenset({
    "id",
    "lifecycle",
    "location_id",
    "city_label",
    "slug_prefix",
    "timezone",
    "display_unit",
    "wu_history_id",
    "icao",
    "lat",
    "lon",
    "sources",
    "leading_obs",
    "coastal",
    "resolution_source",
    "open_meteo_model",
    "label_source",
    "print_cutoff",
    "replaces_builtin",
    "iem_special_schedule_minute",
})
LABEL_SOURCE_FIELDS = frozenset({
    "endpoint",
    "report_types",
    "temperature_field",
    "local_date_basis",
    "dedupe_key",
    "daily_value",
    "complete_day_max_gap_minutes",
    "cross_check",
    "rule_status",
})
PRINT_CUTOFF_FIELDS = frozenset({
    "cutoff_hours_local",
    "alias_window_minutes",
    "admits",
    "effective_cutoff",
})


class CandidateRegistryError(ValueError):
    """The candidate registry is malformed or would collide with production."""


@dataclass(frozen=True)
class LabelSource:
    name: str
    endpoint: str
    report_types: tuple
    temperature_field: str
    local_date_basis: str
    dedupe_key: str
    daily_value: str
    complete_day_max_gap_minutes: int
    cross_check: str
    rule_status: str = ""


@dataclass(frozen=True)
class PrintCutoff:
    name: str
    cutoff_hours_local: tuple
    alias_window_minutes: int


@dataclass(frozen=True)
class CandidateMarket:
    spec: MarketSpec
    location_id: str
    open_meteo_model: str
    label_source: LabelSource
    print_cutoff: PrintCutoff
    replaces_builtin: str = ""
    # IEM files a station's off-hour half-hourly routine METARs as report_type=4
    # (no METAR/SPECI prefix in IEM raw text). That minute, measured per station
    # from the type-4 files, marks a scheduled routine report; null when type 4
    # holds only true SPECIs (US stations).
    iem_special_schedule_minute: int | None = None

    @property
    def id(self):
        return self.spec.id


def _require_fields(row, allowed, required, label):
    keys = set(row or {})
    unknown = sorted(keys - allowed)
    missing = sorted(required - keys)
    if unknown:
        raise CandidateRegistryError(f"{label}: unknown fields {', '.join(unknown)}")
    if missing:
        raise CandidateRegistryError(f"{label}: missing fields {', '.join(missing)}")


def _label_source(name, payload):
    _require_fields(payload, LABEL_SOURCE_FIELDS, LABEL_SOURCE_FIELDS - {"rule_status"}, f"label source {name}")
    report_types = tuple(int(item) for item in payload["report_types"])
    if not report_types:
        raise CandidateRegistryError(f"label source {name}: report_types is empty")
    gap = int(payload["complete_day_max_gap_minutes"])
    if gap <= 0:
        raise CandidateRegistryError(f"label source {name}: complete_day_max_gap_minutes must be positive")
    return LabelSource(
        name=name,
        endpoint=str(payload["endpoint"]),
        report_types=report_types,
        temperature_field=str(payload["temperature_field"]),
        local_date_basis=str(payload["local_date_basis"]),
        dedupe_key=str(payload["dedupe_key"]),
        daily_value=str(payload["daily_value"]),
        complete_day_max_gap_minutes=gap,
        cross_check=str(payload["cross_check"]),
        rule_status=str(payload.get("rule_status", "")),
    )


def _print_cutoff(name, payload):
    _require_fields(payload, PRINT_CUTOFF_FIELDS, PRINT_CUTOFF_FIELDS, f"print cutoff {name}")
    hours = tuple(int(item) for item in payload["cutoff_hours_local"])
    if not hours or list(hours) != sorted(set(hours)) or not all(0 <= hour <= 23 for hour in hours):
        raise CandidateRegistryError(f"print cutoff {name}: cutoff_hours_local must be sorted unique hours")
    alias = int(payload["alias_window_minutes"])
    if not 0 <= alias < 60:
        raise CandidateRegistryError(f"print cutoff {name}: alias_window_minutes must be 0-59")
    return PrintCutoff(name=name, cutoff_hours_local=hours, alias_window_minutes=alias)


def parse_candidate_registry(payload: Mapping) -> dict:
    """Validate a candidate registry payload and return ``{id: CandidateMarket}``."""
    if not isinstance(payload, Mapping):
        raise CandidateRegistryError("candidate registry must be a JSON object")
    if payload.get("schema_version") != MARKET_REGISTRY_SCHEMA_VERSION:
        raise CandidateRegistryError(
            f"candidate registry schema must be {MARKET_REGISTRY_SCHEMA_VERSION!r}"
        )
    if payload.get("status") != CANDIDATE_REGISTRY_STATUS:
        raise CandidateRegistryError(f"candidate registry status must be {CANDIDATE_REGISTRY_STATUS!r}")
    label_sources = {
        str(name): _label_source(str(name), body)
        for name, body in (payload.get("label_sources") or {}).items()
    }
    print_cutoffs = {
        str(name): _print_cutoff(str(name), body)
        for name, body in (payload.get("print_cutoffs") or {}).items()
    }
    builtins = {spec.id: spec for spec in BUILTIN_SPECS}
    builtin_ids = set(builtins)
    builtin_prefixes = {spec.slug_prefix for spec in BUILTIN_SPECS}
    builtin_icaos = {spec.icao for spec in BUILTIN_SPECS}
    markets = {}
    for index, row in enumerate(payload.get("markets") or []):
        label = f"candidate row {index}"
        required = CANDIDATE_ROW_FIELDS - {"coastal", "replaces_builtin"}
        schedule_minute = row.get("iem_special_schedule_minute")
        if schedule_minute is not None and (
            isinstance(schedule_minute, bool) or not isinstance(schedule_minute, int) or not 0 <= schedule_minute < 60
        ):
            raise CandidateRegistryError(f"{label}: iem_special_schedule_minute must be null or 0-59")
        _require_fields(row, CANDIDATE_ROW_FIELDS, required, label)
        if row.get("lifecycle") != CANDIDATE_LIFECYCLE:
            raise CandidateRegistryError(
                f"{label}: lifecycle must be {CANDIDATE_LIFECYCLE!r}; activation is a reviewed MarketSpec change"
            )
        if "enabled" in row:
            raise CandidateRegistryError(f"{label}: candidate rows carry no enabled switch")
        spec = market_spec_from_mapping(row)
        if spec.id in markets:
            raise CandidateRegistryError(f"{label}: duplicate id {spec.id!r}")
        replaces = str(row.get("replaces_builtin") or "")
        if replaces and replaces not in builtins:
            raise CandidateRegistryError(f"{label}: replaces_builtin {replaces!r} is not a built-in market")
        # A station-change candidate (replaces_builtin) shares only the venue slug prefix of the
        # built-in it would replace; its id and station never collide with any built-in.
        shared_prefix = builtins[replaces].slug_prefix if replaces else None
        prefix_collides = spec.slug_prefix in builtin_prefixes and spec.slug_prefix != shared_prefix
        if spec.id in builtin_ids or prefix_collides or spec.icao in builtin_icaos:
            raise CandidateRegistryError(f"{label}: {spec.id!r} collides with a built-in market")
        if replaces and spec.timezone != builtins[replaces].timezone:
            raise CandidateRegistryError(f"{label}: timezone differs from the built-in it replaces")
        if replaces and spec.display_unit != builtins[replaces].display_unit:
            raise CandidateRegistryError(f"{label}: unit differs from the built-in it replaces")
        if spec.display_unit not in {"C", "F"}:
            raise CandidateRegistryError(f"{label}: display_unit must be C or F")
        spec.tz  # noqa: B018 - raises for an unknown IANA zone
        for field in ("resolution_source", "leading_obs"):
            if getattr(spec, field) not in spec.sources:
                raise CandidateRegistryError(f"{label}: {field} is not listed in sources")
        if row["label_source"] not in label_sources:
            raise CandidateRegistryError(f"{label}: unknown label_source {row['label_source']!r}")
        if row["print_cutoff"] not in print_cutoffs:
            raise CandidateRegistryError(f"{label}: unknown print_cutoff {row['print_cutoff']!r}")
        markets[spec.id] = CandidateMarket(
            spec=spec,
            location_id=str(row["location_id"]),
            open_meteo_model=str(row["open_meteo_model"]),
            label_source=label_sources[row["label_source"]],
            print_cutoff=print_cutoffs[row["print_cutoff"]],
            replaces_builtin=replaces,
            iem_special_schedule_minute=schedule_minute,
        )
    if not markets:
        raise CandidateRegistryError("candidate registry has no rows")
    return markets


def load_candidate_registry(path: str | Path | None = None) -> dict:
    path = Path(path or CANDIDATE_REGISTRY_PATH)
    with path.open("r", encoding="utf-8") as handle:
        return parse_candidate_registry(json.load(handle))


def candidate_market(market_id: str, path: str | Path | None = None) -> CandidateMarket:
    registry = load_candidate_registry(path)
    if market_id not in registry:
        raise CandidateRegistryError(f"unknown candidate market id: {market_id!r}")
    return registry[market_id]


def _check(path):
    registry = load_candidate_registry(path)
    rows = [
        {
            "id": item.id,
            "icao": item.spec.icao,
            "timezone": item.spec.timezone,
            "unit": item.spec.display_unit,
            "label_source": item.label_source.name,
            "print_cutoff": item.print_cutoff.name,
            "open_meteo_model": item.open_meteo_model,
            "replaces_builtin": item.replaces_builtin,
            "iem_special_schedule_minute": item.iem_special_schedule_minute,
        }
        for item in registry.values()
    ]
    return {"status": "PASS", "path": str(path or CANDIDATE_REGISTRY_PATH), "markets": rows}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate the inactive candidate market registry.")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="Validate the registry and print its rows.")
    check.add_argument("--registry", default="")
    args = parser.parse_args(argv)
    if args.command == "check":
        print(json.dumps(_check(args.registry or None), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
