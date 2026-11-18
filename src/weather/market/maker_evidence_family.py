"""Config-driven passive capture families, recorded beside (never inside) the 88a root.

A family in ``config/capture_families.json`` names per-city event-slug prefixes of
one non-core market family. Its recorder keeps every active condition's minute
books and reward terms in ``data/maker_evidence_families/<id>``. It ranks and
selects nothing, opens no websocket, and stops at its own free-space floor,
above the 88a critical brake, so the core recorder keeps the disk first.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import json
from pathlib import Path
import re

from weather.market.market_config import MONTH_NAMES
from weather.market.market_registry import all_specs
from weather.market.maker_evidence_public import reward_rate, reward_record
from weather.market.maker_evidence_store import digest, encoded
from weather.paths import config_path, data_path

FAMILY_CONFIG = config_path("capture_families.json")
FAMILY_ID = re.compile(r"[a-z][a-z0-9_]{0,40}\Z")
SLUG_PREFIX = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*-on\Z")
BOUNDS = {"max_conditions": (1, 1200), "reward_sweep_minutes": (1, 60),
          "max_reward_reads_per_cycle": (1, 100), "stop_below_free_gib": (40, 900)}


@dataclass(frozen=True)
class CaptureFamily:
    id: str
    markets: tuple            # ((MarketSpec, event slug prefix), ...)
    day_ahead: tuple
    max_conditions: int
    reward_sweep_minutes: int
    max_reward_reads_per_cycle: int
    stop_below_free_gib: int
    config_sha256: str

    @property
    def root(self):
        return data_path("maker_evidence_families", self.id)

    @property
    def floor_bytes(self):
        return self.stop_below_free_gib * 1024**3


def load_family(family_id, path=FAMILY_CONFIG, *, specs=None):
    raw = Path(path).read_bytes()
    if len(raw) > 65536:
        raise ValueError("capture family config exceeds byte limit")
    payload = json.loads(raw.decode("utf-8-sig"))
    if payload.get("format_version") != 1 or not FAMILY_ID.fullmatch(str(family_id)):
        raise ValueError("unsupported capture family config or id")
    if family_id not in payload.get("families", {}):
        raise ValueError(f"unknown capture family: {family_id}")
    row = payload["families"][family_id]
    registry = {spec.id: spec for spec in (all_specs() if specs is None else specs)}
    markets, excluded = row["markets"], row.get("excluded_markets", {})
    prefixes = list(markets.values())
    if (not markets or (set(markets) | set(excluded)) - set(registry) or set(markets) & set(excluded)
            or len(set(prefixes)) != len(prefixes) or not all(isinstance(p, str) and SLUG_PREFIX.fullmatch(p)
                                                               for p in prefixes)):
        raise ValueError("family markets must be distinct registry ids with valid, unique slug prefixes")
    if any(prefix == registry[city].slug_prefix for city, prefix in markets.items()):
        raise ValueError("a capture family never re-captures the core 88a family")
    days = row["day_ahead"]
    if (not isinstance(days, list) or not days or len(set(days)) != len(days)
            or not all(type(day) is int and 0 <= day <= 6 for day in days)):
        raise ValueError("day_ahead must be distinct integers 0..6")
    limits = {key: row[key] for key in BOUNDS}
    if not all(type(value) is int and BOUNDS[key][0] <= value <= BOUNDS[key][1] for key, value in limits.items()):
        raise ValueError("family limits out of bounds")
    return CaptureFamily(id=family_id, markets=tuple((registry[city], prefix) for city, prefix in markets.items()),
                         day_ahead=tuple(days), config_sha256=digest(raw), **limits)


def event_slug(prefix, target_date):
    return f"{prefix}-{MONTH_NAMES[target_date.month]}-{target_date.day}-{target_date.year}"


def expected_events(family, now):
    return {event_slug(prefix, now.astimezone(spec.tz).date() + timedelta(days=day)): (spec.id, day)
            for spec, prefix in family.markets for day in family.day_ahead}


def reward_terms(reward, today):
    return {"daily_rate": reward_rate(reward, today), "min_size": reward["rewards_min_size"],
            "max_spread_cents": reward["rewards_max_spread"]}


def due_reward_reads(rows, state, family, now):
    """Changed Gamma terms first, then never-read, then oldest past the sweep; capped per cycle."""
    sweep = timedelta(minutes=family.reward_sweep_minutes)
    due = []
    for row in rows:
        prior = state.get(row["condition_id"])
        terms = digest(encoded(row["reward"]))
        if prior is None:
            due.append((1, "", row["condition_id"]))
        elif prior["gamma_terms_sha256"] != terms:
            due.append((0, prior["checked_at_utc"], row["condition_id"]))
        elif now - prior["checked_at"] >= sweep:
            due.append((2, prior["checked_at_utc"], row["condition_id"]))
    return [cid for _, _, cid in sorted(due)[:family.max_reward_reads_per_cycle]]


def family_universe(reader, family, *, now, reward_state, discover):
    """Every active condition of the family's T+day events; reward records on change or sweep.

    ``discover`` is the core recorder's Gamma event discovery, passed in so this
    module never imports the capture entry point.
    """
    expected = expected_events(family, now)
    discovered, missing = discover(reader, expected)
    if len(discovered) > family.max_conditions:
        raise ValueError("family condition universe exceeds its bound")
    today = now.date().isoformat()
    rows = sorted(discovered.values(), key=lambda row: (row["city"], row["day_ahead"], row["condition_id"]))
    for cid in set(reward_state) - set(discovered):
        del reward_state[cid]
    for cid in due_reward_reads(rows, reward_state, family, now):
        record = reward_record(reader, cid, partition=family.id)
        reward_state[cid] = {"checked_at": now, "checked_at_utc": now.isoformat(),
                             "gamma_terms_sha256": digest(encoded(discovered[cid]["reward"])),
                             "clob_reward_content_sha256": digest(encoded(record)),
                             "clob_daily_rate": reward_rate(record, today) if record else 0.}
    universe = []
    for row in rows:
        clob = reward_state.get(row["condition_id"], {})
        universe.append({"condition_id": row["condition_id"], "family": family.id, "city": row["city"],
                         "day_ahead": row["day_ahead"], "event_slug": row["event_slug"], "tokens": row["tokens"],
                         "reward_terms": reward_terms(row["reward"], today),
                         "clob_reward_content_sha256": clob.get("clob_reward_content_sha256"),
                         "clob_daily_rate": clob.get("clob_daily_rate")})
    for spec, _ in family.markets:
        value = {"family": family.id, "city": spec.id,
                 "bands": [row for row in universe if row["city"] == spec.id],
                 "missing_events": sorted(slug for slug in missing if expected[slug][0] == spec.id),
                 "selection": "every active condition; no ranking"}
        # Change-only: an unchanged city universe references its prior body.
        reader.store.record("universe", encoded(value), change_key=f"universe:{family.id}:{spec.id}",
                            partition=f"{family.id}-{spec.id}")
    return universe, [], sorted(missing)
