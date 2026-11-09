"""Frozen F3 simulation inputs and explicit-path stdlib configuration loaders.

No live policy or universe reader is imported. Decimal strings are mandatory
for monetary configuration; the example is never a freeze receipt.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Literal, Mapping
from zoneinfo import ZoneInfo

POLICY_SCHEMA = "f3_policy_v1"
STRATA_SCHEMA = "f3_strata_v1"
NWP_SCHEMA = "f3_nwp_release_schedule_v1"
D = Decimal


@dataclass(frozen=True)
class Level:
    price: Decimal
    size: Decimal


@dataclass(frozen=True)
class TokenBook:
    bids: tuple[Level, ...]
    asks: tuple[Level, ...]
    tick: Decimal
    min_order_size: Decimal


@dataclass(frozen=True)
class BookState:
    state: Literal["known", "unknown"]
    yes: TokenBook | None
    no: TokenBook | None
    received_at_utc: datetime | None


@dataclass(frozen=True)
class Terms:
    rate_daily_pusd: Decimal
    min_size: Decimal
    max_spread_cents: Decimal
    fee_taker_coefficient: Decimal | None
    fee_maker: Decimal | None
    rebate_fraction: Decimal | None
    post_only_available: bool = True


@dataclass(frozen=True)
class UniverseCity:
    slug: str
    timezone: str
    station_id: str
    settlement_kind: str
    families: tuple[str, ...]


@dataclass(frozen=True)
class ObsState:
    routine_obs_utc: tuple[datetime, ...]
    running_extreme_bin: str | None
    neighbour_bins: tuple[str, ...]


@dataclass(frozen=True)
class BandCandidate:
    city: str
    family: Literal["highest", "lowest"]
    event_date_local: date
    condition_id: str
    token_ids: tuple[str, str]
    event_condition_ids: tuple[str, ...]
    book: BookState
    terms: Terms | None
    cell: str
    cluster: str
    possible: bool | None = None
    obs: ObsState | None = None

    @property
    def cfd_key(self) -> str:
        return f"{self.city}:{self.family}:{self.event_date_local.isoformat()}"

    @property
    def band_key(self) -> str:
        return f"{self.city}:{self.family}"


@dataclass(frozen=True)
class QuotePair:
    adjusted_mid: Decimal
    yes_buy: Decimal
    no_buy: Decimal
    size: Decimal
    reserve_pusd: Decimal
    distances_cents: tuple[Decimal, Decimal]
    own_q_min: Decimal  # Decimal(str(F2 float)); pair_score is the Decimal model.
    share_many: float


@dataclass(frozen=True)
class Refusal:
    code: str
    detail: str = ""


@dataclass(frozen=True)
class GuardHit:
    guard: str
    action: Literal["no_post", "cancel", "retire", "exclude_day"]
    detail: str = ""


@dataclass(frozen=True)
class Window:
    start_utc: datetime
    end_utc: datetime
    source: str


@dataclass(frozen=True)
class EnvelopeCell:
    cell: str
    shape: Literal["additive", "proportional"]
    a_q80: Decimal | None
    kappa_q80: Decimal | None
    tau_r_min: Decimal
    validated: bool


@dataclass(frozen=True)
class CapitalState:
    funding: Decimal
    inventory: Decimal
    resting: Decimal
    losses: Decimal
    costs: Decimal
    available_gains: Decimal  # Proved retained redemption gains ONLY, never rewards/rebates.
    profit: Decimal
    incentives: Decimal
    external: Decimal
    basis: Literal["gross", "net_of_retained_gains"]


@dataclass(frozen=True)
class SimCashState:
    """Caller assertions for the reconciled clean simulation parity domain."""
    available: Decimal
    expected: Decimal
    quarantined_after_bridge: Decimal = D(0)
    bridge_exists: bool = True
    ledger_halted: bool = False
    ledger_mismatches: bool = False
    unknown_outgoing_activity: bool = False
    blocking_legacy_activity: bool = False
    unknown_activity: bool = False


class F3NotReconciled(ValueError):
    """A caller supplied a state outside F3's gate equivalence domain."""
    def __init__(self, field: str):
        self.field = field
        super().__init__(field)


@dataclass(frozen=True)
class BandDayUsage:
    filled: Decimal
    resting: Decimal
    unmapped_legacy: Decimal = D(0)


@dataclass(frozen=True)
class PortfolioState:
    capital: CapitalState
    cash: SimCashState
    active_bands: Mapping[str, str]
    quoted_cfds: frozenset[str]
    band_day_usage: Mapping[tuple[str, str], BandDayUsage]
    per_market_open: Mapping[str, Decimal]
    held_conditions: frozenset[str]


@dataclass(frozen=True)
class FeeExpected:
    taker_coefficient: Decimal = D("0.05")
    maker: Decimal = D(0)
    rebate_fraction: Decimal = D("0.25")


@dataclass(frozen=True)
class ObsGuardConfig:
    window_minutes: tuple[int, int] = (-5, 5)
    widen_to_cents: Decimal = D(3)
    neighbour_bins: int = 1


@dataclass(frozen=True)
class F3Params:
    schema_version: str = POLICY_SCHEMA
    policy_id: str = "T5-R"
    f2_source: Mapping[str, str | None] = field(default_factory=lambda: MappingProxyType(
        dict(git_sha=None, policy_sha256=None, freeze_receipt_sha256=None)))
    stratum: str = "H-PRE"
    local_event_dte: tuple[int, ...] = (1,)
    retire_local_time: time = time(23, 45)
    tokens: tuple[str, ...] = ("YES", "NO")
    shares_per_leg: Decimal = D(20)
    tick_pusd: Decimal = D("0.01")
    quote_offset_pusd: Decimal = D("0.015")
    requote_distance_cents: tuple[Decimal, Decimal] = (D(1), D(3))
    leg_price_range: tuple[Decimal, Decimal] = (D("0.17"), D("0.80"))
    share_many_range: tuple[Decimal, Decimal] = (D(0), D(1))
    min_reward_rate: Decimal = D(0)
    min_book_depth: Decimal = D(20)
    per_order_cap_pusd: Decimal = D("15.80")
    per_band_cap_pusd: Decimal = D("19.60")
    per_band_daily_filled_cap_pusd: Decimal = D(40)
    fill_cooldown_seconds: int = 60
    on_first_band_fill: str = "cancel_reconcile_cooldown_and_requote_same_band"
    replace_retired_band: bool = False
    sleeve_ceiling_pusd: Decimal = D(300)
    sleeve_loss_basis: Literal["gross", "net_of_retained_gains"] = "net_of_retained_gains"
    max_concurrent_bands: int = 15
    max_bands_per_cluster: int = 3
    min_expected_reward_pusd_per_day: Decimal = D("0.05")
    decision_tick_seconds: int = 60
    fee_expected: FeeExpected = field(default_factory=FeeExpected)
    g_obs: ObsGuardConfig = field(default_factory=ObsGuardConfig)
    strata_path: str = "config/f3/strata.json"
    nwp_schedule_path: str = "config/f3/nwp_release_schedule.json"


@dataclass(frozen=True)
class GateResult:
    ok: bool
    code: str | None
    figures: Mapping[str, Decimal]


@dataclass(frozen=True)
class Selection:
    picks: tuple[tuple[BandCandidate, QuotePair, Decimal], ...]
    refusals: Mapping[str, int]


@dataclass(frozen=True)
class Strata:
    schema_version: str
    grid_declared: str
    universe_pin: Mapping[str, str | None]
    region_rule: str
    utc_blocks: tuple[str, ...]
    cells: tuple[str, ...]
    arms: Mapping[str, Mapping[str, object]]
    region_of: Mapping[str, str]
    cluster_of: Mapping[str, str]


@dataclass(frozen=True)
class NwpRelease:
    model: str
    cycle_utc: str
    available_utc: time
    basis: str
    day_offset: int = 0


@dataclass(frozen=True)
class NwpSchedule:
    schema_version: str
    source: str
    before_minutes: int
    after_minutes: int
    lengthen_only: bool
    releases: tuple[NwpRelease, ...]


def _decimal(value) -> Decimal:
    if not isinstance(value, str):
        raise ValueError("decimal string required")
    try:
        result = D(value)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal") from exc
    if not result.is_finite() or result < 0:
        raise ValueError("nonnegative finite decimal required")
    return result


def _clock(value) -> time:
    if not isinstance(value, str) or not re.fullmatch(r"[0-2][0-9]:[0-5][0-9]", value):
        raise ValueError("HH:MM required")
    return time.fromisoformat(value)


def _keys(row, names):
    if not isinstance(row, dict) or set(row) != set(names):
        raise ValueError("configuration keys")


def policy_from_mapping(row: Mapping[str, object]) -> F3Params:
    """Validate a policy mapping; shared with the pure F2-field adapter."""
    row = dict(row)
    _keys(row, (f.name for f in fields(F3Params)))
    decimal_keys = ("shares_per_leg", "tick_pusd", "quote_offset_pusd", "min_reward_rate",
                    "min_book_depth", "per_order_cap_pusd", "per_band_cap_pusd",
                    "per_band_daily_filled_cap_pusd", "sleeve_ceiling_pusd",
                    "min_expected_reward_pusd_per_day")
    for key in decimal_keys:
        row[key] = _decimal(row[key])
    for key in ("requote_distance_cents", "leg_price_range", "share_many_range"):
        if not isinstance(row[key], list) or len(row[key]) != 2:
            raise ValueError(key)
        row[key] = tuple(map(_decimal, row[key]))
        if row[key][0] > row[key][1]:
            raise ValueError(key)
    row["retire_local_time"] = _clock(row["retire_local_time"])
    if row["local_event_dte"] != [1] or type(row["local_event_dte"][0]) is not int or row["tokens"] != ["YES", "NO"]:
        raise ValueError("T5-R horizon/tokens")
    row["local_event_dte"], row["tokens"] = (1,), ("YES", "NO")
    source = row["f2_source"]
    _keys(source, ("git_sha", "policy_sha256", "freeze_receipt_sha256"))
    for key, width in (("git_sha", 40), ("policy_sha256", 64), ("freeze_receipt_sha256", 64)):
        if source[key] is not None and not re.fullmatch(r"[0-9a-f]{" + str(width) + "}", str(source[key])):
            raise ValueError("f2_source." + key)
    row["f2_source"] = MappingProxyType(dict(source))
    _keys(row["fee_expected"], ("taker_coefficient", "maker", "rebate_fraction"))
    row["fee_expected"] = FeeExpected(**{k: _decimal(v) for k, v in row["fee_expected"].items()})
    obs = row["g_obs"]
    _keys(obs, ("window_minutes", "widen_to_cents", "neighbour_bins"))
    if (obs["window_minutes"] != [-5, 5] or type(obs["neighbour_bins"]) is not int or
            obs["neighbour_bins"] != 1 or _decimal(obs["widen_to_cents"]) < 3):
        raise ValueError("g_obs")
    row["g_obs"] = ObsGuardConfig((-5, 5), _decimal(obs["widen_to_cents"]), 1)
    for key in ("fill_cooldown_seconds", "max_concurrent_bands", "max_bands_per_cluster", "decision_tick_seconds"):
        if type(row[key]) is not int or row[key] <= 0:
            raise ValueError(key)
    if (row["schema_version"] != POLICY_SCHEMA or row["policy_id"] != "T5-R" or row["stratum"] != "H-PRE" or
            row["shares_per_leg"] != 20 or row["tick_pusd"] != D(".01") or
            not D(".005") <= row["quote_offset_pusd"] <= D(".05") or
            not D(".5") <= row["requote_distance_cents"][0] <= row["requote_distance_cents"][1] <= 6 or
            not 0 < row["leg_price_range"][0] <= row["leg_price_range"][1] < 1 or
            not 0 <= row["share_many_range"][0] <= row["share_many_range"][1] <= 1 or
            not 0 < row["per_order_cap_pusd"] <= 16 or not 0 < row["per_band_cap_pusd"] <= 20 or
            not 0 < row["per_band_daily_filled_cap_pusd"] <= 300 or row["sleeve_ceiling_pusd"] != 300 or
            row["fill_cooldown_seconds"] < 60 or row["max_concurrent_bands"] > 15 or
            row["max_bands_per_cluster"] > 3 or row["replace_retired_band"] is not False or
            row["on_first_band_fill"] != "cancel_reconcile_cooldown_and_requote_same_band" or
            row["sleeve_loss_basis"] not in ("gross", "net_of_retained_gains")):
        raise ValueError("unsupported F3 policy")
    for key in ("strata_path", "nwp_schedule_path"):
        if not isinstance(row[key], str) or not row[key].startswith("config/f3/") or ".." in row[key].split("/"):
            raise ValueError(key)
    return F3Params(**row)


def load_policy(path: Path) -> F3Params:
    return policy_from_mapping(json.loads(path.read_text(encoding="utf-8")))


def load_strata(path: Path) -> Strata:
    row = json.loads(path.read_text(encoding="utf-8"))
    _keys(row, (f.name for f in fields(Strata)))
    blocks = ("00-06", "06-12", "12-18", "18-24")
    cells = tuple(f"H-PRE|{block}|{region}" for block in blocks for region in ("AEA", "AP"))
    if row["schema_version"] != STRATA_SCHEMA or tuple(row["utc_blocks"]) != blocks or tuple(row["cells"]) != cells:
        raise ValueError("strata grid")
    if set(row["arms"]) != {"T5-R", "D-LOW"}:
        raise ValueError("strata arms")
    cities = set()
    arms = {}
    for arm, family in (("T5-R", "highest"), ("D-LOW", "lowest")):
        spec = row["arms"][arm]
        _keys(spec, ("family", "cities"))
        if (spec["family"] != family or not isinstance(spec["cities"], list) or
                len(spec["cities"]) != len(set(spec["cities"])) or not all(isinstance(c, str) and c for c in spec["cities"])):
            raise ValueError("strata cities")
        cities.update(spec["cities"])
        arms[arm] = MappingProxyType(dict(family=family, cities=tuple(spec["cities"])))
    if set(row["region_of"]) != cities or set(row["cluster_of"]) != cities:
        raise ValueError("strata city maps")
    if (not set(row["region_of"].values()) <= {"AEA", "AP"} or
            not all(isinstance(v, str) and v for v in row["cluster_of"].values())):
        raise ValueError("strata region/cluster")
    _keys(row["universe_pin"], ("path", "schema_version", "sha256"))
    if row["universe_pin"]["schema_version"] != "weather-universe-v1":
        raise ValueError("universe schema")
    pin = row["universe_pin"]["sha256"]
    if pin is not None and (not isinstance(pin, str) or not re.fullmatch(r"[0-9a-f]{64}", pin)):
        raise ValueError("universe pin")
    for key in ("universe_pin", "region_of", "cluster_of"):
        row[key] = MappingProxyType(dict(row[key]))
    row.update(utc_blocks=blocks, cells=cells, arms=MappingProxyType(arms))
    return Strata(**row)


def load_nwp_schedule(path: Path) -> NwpSchedule:
    row = json.loads(path.read_text(encoding="utf-8"))
    _keys(row, ("schema_version", "source", "window_minutes", "lengthen_only", "releases"))
    _keys(row["window_minutes"], ("before", "after"))
    before, after = (row["window_minutes"][k] for k in ("before", "after"))
    if (row["schema_version"] != NWP_SCHEMA or row["lengthen_only"] is not True or
            type(before) is not int or type(after) is not int or before < 5 or after < 30):
        raise ValueError("NWP lengthen-only floor")
    releases, seen = [], set()
    for spec in row["releases"]:
        _keys(spec, {"model", "cycle_utc", "available_utc", "basis"} | ({"day_offset"} if "day_offset" in spec else set()))
        key = (spec["model"], spec["cycle_utc"])
        offset = spec.get("day_offset", 0)
        if (key in seen or key[0] not in ("GFS", "AIFS", "IFS_HRES_open") or key[1] not in ("00", "06", "12", "18") or
                type(offset) is not int or offset not in (0, 1) or
                spec["basis"] not in ("measured_00z", "assumed_plus_6h")):
            raise ValueError("NWP duplicate/invalid release")
        seen.add(key)
        releases.append(NwpRelease(key[0], key[1], _clock(spec["available_utc"]), spec["basis"], offset))
    if len(seen) != 12:
        raise ValueError("NWP complete release grid required")
    return NwpSchedule(NWP_SCHEMA, row["source"], before, after, True, tuple(releases))


def load_universe(path: Path) -> dict[str, UniverseCity]:
    row = json.loads(path.read_text(encoding="utf-8"))
    if row.get("schema_version") != "weather-universe-v1" or not isinstance(row.get("cities"), list):
        raise ValueError("universe schema")
    cities = {}
    for spec in row["cities"]:
        if not isinstance(spec, dict) or not {"slug", "timezone", "station_id", "settlement_kind", "families"} <= set(spec):
            raise ValueError("universe city fields")
        slug = spec["slug"]
        if not isinstance(slug, str) or not slug or slug in cities:
            raise ValueError("universe city identity")
        ZoneInfo(spec["timezone"])
        families = tuple(spec["families"])
        if not families or len(set(families)) != len(families) or not set(families) <= {"highest", "lowest"}:
            raise ValueError("universe families")
        cities[slug] = UniverseCity(slug, spec["timezone"], spec["station_id"], spec["settlement_kind"], families)
    return cities
