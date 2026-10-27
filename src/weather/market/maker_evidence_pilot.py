"""Recorder-only rows for the core 88a recorder (data layer v2 S2, VR-1 pilot P1).

The ``core_recorder_only`` block of ``config/capture_families.json`` (default path, no CLI
argument) names extra venue markets that the core recorder captures beside the built-ins:
minute books, change-triggered reward records and public trades, ranked with the same
top-ten-per-city rule. It is re-read every cycle; its whole-file SHA-256 is stamped on
every pilot universe row and in status.

Contract (docs/operations/DATA_LAYER_V2_CONTRACT.md "Recorder-only rows"):

* The 12 built-ins stay enumerated from ``all_specs()``. A row may never name a built-in
  id or slug prefix, nor a capture family's prefix, so no config state can change the
  built-ins' selection (owner Q16: pilot bands are outside the 10-01 maker-P&L
  pre-registration's 12-market stratum).
* Pilot rows are journaled only in ``pilot`` partitions and on the ``pilot_trades``
  channel; the built-in journals (``books``, ``ranking_books``, ``trades``,
  ``universe-<city>``) never receive a pilot row.
* A malformed block switches the pilot off for that cycle; it never stops built-in capture.
* Landing defaults are inert: ``pilot`` and ``rewards_sweep`` are ``off`` and
  ``built_in_reward_cadence`` is ``legacy`` (owner 10-15 via master: the 88a desk-study panel
  holds to UTC 10-30, so built-in bands keep the every-minute reward read until
  ``BUILT_IN_LEGACY_UNTIL`` whatever the config says). Switching on is a config-only change.

This module never imports the capture entry point.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from weather.market.maker_evidence_family import FAMILY_CONFIG, SLUG_PREFIX, event_slug
from weather.market.maker_evidence_store import digest
from weather.market.market_registry import all_specs

BLOCK = "core_recorder_only"
PILOT_PARTITION = "pilot"
PILOT_TRADES_CHANNEL = "pilot_trades"
STRATUM = "outside_10_01_maker_pnl_prereg_12_market_stratum"
# P1 is five cities; P4 tranches arrive by config. A larger universe is a code change.
MAX_ROWS = 10
ROW_ID = re.compile(r"[a-z][a-z0-9_]{0,40}\Z")
SERIES_PREFIX = {"highest": "highest-temperature-in-", "lowest": "lowest-temperature-in-"}
BAND_POLICIES = ("top10_reward_ranked",)
HORIZONS = (0, 1, 2)
ROW_FIELDS = {"id", "location_id", "series", "slug_prefix", "tz", "horizons", "band_policy"}
SWEEP_STATES = ("on", "off")
PILOT_STATES = ("on", "off")
# Built-in reward-read cadence. ``legacy`` is the pre-S9 every-minute read of each selected
# band's record; ``event_driven`` is the S9 trigger. Before the panel hold ends the built-ins
# stay legacy even when the config says otherwise (dry runs excepted: their root is scratch).
CADENCES = ("legacy", "event_driven")
BUILT_IN_LEGACY_UNTIL = datetime(2026, 10, 31, tzinfo=timezone.utc)


@dataclass(frozen=True)
class RecorderOnlyMarket:
    """Duck-typed like ``MarketSpec`` where the universe builder needs it (id, tz, slug_prefix)."""

    id: str
    location_id: str
    series: str
    slug_prefix: str
    tz: ZoneInfo
    horizons: tuple
    band_policy: str


@dataclass(frozen=True)
class RecorderOnlyConfig:
    markets: tuple
    rewards_sweep: str
    config_sha256: str
    pilot: str = "off"
    built_in_reward_cadence: str = "legacy"

    @property
    def sweep_enabled(self):
        return self.rewards_sweep == "on"

    @property
    def pilot_enabled(self):
        return self.pilot == "on"

    @property
    def active_markets(self):
        """The rows captured this cycle: none while the pilot switch is off."""
        return self.markets if self.pilot_enabled else ()


def built_ins_event_driven(config, now, *, dry_run=False):
    """True only when the config asks for it and the panel hold has ended (or a scratch dry run)."""
    return (config is not None and config.built_in_reward_cadence == "event_driven"
            and (dry_run or now >= BUILT_IN_LEGACY_UNTIL))


def _family_prefixes(payload):
    prefixes = set()
    for row in (payload.get("families") or {}).values():
        prefixes.update(str(prefix) for prefix in (row.get("markets") or {}).values())
    return prefixes


def load_recorder_only(path=FAMILY_CONFIG, *, specs=None):
    """Parse and validate the block; an absent block means no pilot, no sweep, legacy built-ins."""
    raw = Path(path).read_bytes()
    if len(raw) > 65536:
        raise ValueError("capture family config exceeds byte limit")
    payload = json.loads(raw.decode("utf-8-sig"))
    if payload.get("format_version") != 1:
        raise ValueError("unsupported capture family config")
    sha = digest(raw)
    block = payload.get(BLOCK)
    if block is None:
        return RecorderOnlyConfig(markets=(), rewards_sweep="off", config_sha256=sha)
    if not isinstance(block, dict):
        raise ValueError("core_recorder_only must be an object")
    sweep = block.get("rewards_sweep", "off")
    if sweep not in SWEEP_STATES:
        raise ValueError("rewards_sweep must be 'on' or 'off'")
    pilot = block.get("pilot", "off")
    if pilot not in PILOT_STATES:
        raise ValueError("pilot must be 'on' or 'off'")
    cadence = block.get("built_in_reward_cadence", "legacy")
    if cadence not in CADENCES:
        raise ValueError("built_in_reward_cadence must be 'legacy' or 'event_driven'")
    rows = block.get("rows", [])
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise ValueError(f"core_recorder_only rows must be a list of at most {MAX_ROWS}")
    builtins = list(all_specs() if specs is None else specs)
    reserved_ids = {spec.id for spec in builtins}
    reserved_prefixes = {spec.slug_prefix for spec in builtins} | _family_prefixes(payload)
    markets, ids, prefixes = [], set(), set()
    for row in rows:
        if not isinstance(row, dict) or set(row) - {"note"} != ROW_FIELDS:
            raise ValueError("recorder-only row fields must be exactly " + ", ".join(sorted(ROW_FIELDS)))
        row_id, location, series, prefix = row["id"], row["location_id"], row["series"], row["slug_prefix"]
        if not isinstance(row_id, str) or not ROW_ID.fullmatch(row_id) or row_id in ids:
            raise ValueError("recorder-only ids must be unique lowercase identifiers")
        if row_id in reserved_ids or location in reserved_ids:
            raise ValueError("a recorder-only row never names a built-in market (they stay on all_specs())")
        if series not in SERIES_PREFIX:
            raise ValueError("series must be 'highest' or 'lowest'")
        if (not isinstance(prefix, str) or not SLUG_PREFIX.fullmatch(prefix)
                or not prefix.startswith(SERIES_PREFIX[series]) or prefix in prefixes):
            raise ValueError("slug_prefix must be a unique '<series>-temperature-in-<city>-on' prefix")
        if prefix in reserved_prefixes:
            raise ValueError("a recorder-only row never re-captures a built-in or capture-family event")
        if row["band_policy"] not in BAND_POLICIES:
            raise ValueError("band_policy must be one of " + ", ".join(BAND_POLICIES))
        if row["horizons"] != list(HORIZONS):
            raise ValueError("top10_reward_ranked covers horizons [0, 1, 2] exactly")
        try:
            zone = ZoneInfo(str(row["tz"]))
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("tz must be an IANA zone") from None
        ids.add(row_id)
        prefixes.add(prefix)
        markets.append(RecorderOnlyMarket(id=row_id, location_id=str(location), series=series, slug_prefix=prefix,
                                          tz=zone, horizons=HORIZONS, band_policy=row["band_policy"]))
    return RecorderOnlyConfig(markets=tuple(markets), rewards_sweep=sweep, config_sha256=sha, pilot=pilot,
                              built_in_reward_cadence=cadence)


def pilot_slug(market, target_date):
    return event_slug(market.slug_prefix, target_date)


def universe_partition(market_id):
    return f"{PILOT_PARTITION}-{market_id}"
