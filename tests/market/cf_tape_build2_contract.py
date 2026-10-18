"""Copied record contract of item 330 build 2, for the counterfactual tape's compatibility test.

Not a test module. A verbatim-in-substance copy of the record-reading rules of
``origin/claude/maker-toxicity-20261016`` @ 4ae3602fa, so the tape test does not
import that unmerged branch:

* ``src/maker_core/contracts/evidence_embargo.py``: ``refusal`` / ``refuse``;
* ``src/maker_core/quoting/fill_cost.py``: ``FillContext`` (fields, validation, ``from_mapping``);
* ``src/maker_core/replay/toxicity.py``: ``QuoteMinute``, ``Mark``,
  ``CounterfactualFill``, ``parse_record``, ``read_records`` and the identity
  checks at the top of ``fit`` (``check_fit_joins`` here).

4ae3602fa adds two record rules copied here: ``FillContext`` prints strictly
before ``at_utc``, and ``settlement_observed_at_utc`` (required with a
settlement, dated, never before the fill). ``fill_cost.validate_table`` checks a
fitted table, not records, so it is not copied.

When build 2 merges, replace this copy with imports of the real modules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

EXAM_EMBARGO = (date(2026, 9, 30), date(2026, 10, 15))
FIT_LAST_DATE = date(2026, 9, 29)
SCORED_PANEL = (date(2026, 9, 30), date(2026, 11, 13))
PURPOSES = ("read", "fit", "scored")
FEATURE_GROUPS = ("info_clock", "decided", "book", "prints")
HORIZON_SECONDS = {"1m": 60, "5m": 300, "30m": 1800}
BASIS = "counterfactual"
MARK_TOLERANCE = timedelta(seconds=120)


class EmbargoRefused(ValueError):
    pass


class PointInTimeError(ValueError):
    pass


class ToxicityError(ValueError):
    pass


def utc_time(value):
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        raise ValueError("datetime must be UTC-aware")


def as_date(value) -> date:
    if isinstance(value, datetime):
        if value.utcoffset() != timedelta(0):
            raise ValueError("datetime must be UTC-aware")
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if len(text) == 10:
            return date.fromisoformat(text)
        return as_date(datetime.fromisoformat(text.replace("Z", "+00:00")))
    raise TypeError("a date, UTC datetime or ISO string is required")


def refusal(value, purpose):
    day = as_date(value)
    if EXAM_EMBARGO[0] <= day <= EXAM_EMBARGO[1]:
        return f"EMBARGO_EXAM_WINDOW:{day.isoformat()}"
    if purpose == "fit" and day > FIT_LAST_DATE:
        return f"EMBARGO_FIT_AFTER_{FIT_LAST_DATE.isoformat()}:{day.isoformat()}"
    if purpose == "scored" and SCORED_PANEL[0] <= day <= SCORED_PANEL[1]:
        return f"EMBARGO_SCORED_PANEL:{day.isoformat()}"
    return None


def refuse(*values, purpose):
    if purpose not in PURPOSES:
        raise ValueError("unknown embargo purpose")
    for value in values:
        if value is not None and (code := refusal(value, purpose)):
            raise EmbargoRefused(code)


def _finite(value, name, low=None, high=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    if (low is not None and value < low) or (high is not None and value > high):
        raise ValueError(f"{name} out of range")


def _parse_time(value):
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))


@dataclass(frozen=True)
class FillContext:
    at_utc: datetime
    maker_side: str
    horizon_days: int
    minutes_to_close: float
    minutes_from_scheduled_print: float | None
    minutes_since_model_cycle: float | None
    decided_probability: float | None
    book_imbalance: float | None
    depth_shares: float
    last_print_size: float
    burst_prints: int
    sweep_bands: int
    feature_times: Mapping[str, datetime] = field(default_factory=dict)

    def __post_init__(self):
        utc_time(self.at_utc)
        if self.maker_side not in ("YES", "NO"):
            raise ValueError("maker_side must be YES or NO")
        if type(self.horizon_days) is not int or self.horizon_days < 0:
            raise ValueError("horizon_days must be a non-negative int")
        _finite(self.minutes_to_close, "minutes_to_close", 0)
        for name in ("minutes_from_scheduled_print", "minutes_since_model_cycle"):
            if getattr(self, name) is not None:
                _finite(getattr(self, name), name)
        if self.minutes_since_model_cycle is not None and self.minutes_since_model_cycle < 0:
            raise PointInTimeError("model cycle availability after the context instant")
        if self.decided_probability is not None:
            _finite(self.decided_probability, "decided_probability", 0, 1)
        if self.book_imbalance is not None:
            _finite(self.book_imbalance, "book_imbalance", -1, 1)
        _finite(self.depth_shares, "depth_shares", 0)
        _finite(self.last_print_size, "last_print_size", 0)
        for name in ("burst_prints", "sweep_bands"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError(f"{name} must be a non-negative int")
        times = dict(self.feature_times)
        for group, at in times.items():
            if group not in FEATURE_GROUPS:
                raise ValueError(f"unknown feature group {group}")
            utc_time(at)
            if at > self.at_utc:
                raise PointInTimeError(f"feature {group} timestamped after the context instant")
            if group == "prints" and at >= self.at_utc:
                # The print at the instant is the triggering print itself (train/serve leak).
                raise PointInTimeError("prints must be strictly before the context instant")
        object.__setattr__(self, "feature_times", MappingProxyType(times))

    @classmethod
    def from_mapping(cls, payload):
        values = dict(payload)
        values["at_utc"] = _parse_time(values["at_utc"])
        values["feature_times"] = {k: _parse_time(v) for k, v in dict(values.get("feature_times") or {}).items()}
        return cls(**values)


def _time(value):
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    utc_time(result)
    return result


def _day(value):
    return value if isinstance(value, date) and not isinstance(value, datetime) else as_date(value)


@dataclass(frozen=True)
class QuoteMinute:
    condition_id: str
    market_id: str
    event_date: date
    minute_utc: datetime
    context: FillContext
    basis: str = BASIS

    def __post_init__(self):
        utc_time(self.minute_utc)
        if self.basis != BASIS:
            raise ToxicityError("non_counterfactual_record")
        if not self.condition_id or not self.market_id:
            raise ToxicityError("missing_identity")
        if self.context.at_utc > self.minute_utc:
            raise PointInTimeError("minute context after the minute start")


@dataclass(frozen=True)
class Mark:
    observed_at_utc: datetime
    mid_yes: float

    def __post_init__(self):
        utc_time(self.observed_at_utc)
        if isinstance(self.mid_yes, bool) or not math.isfinite(self.mid_yes) or not 0 <= self.mid_yes <= 1:
            raise ToxicityError("invalid_mark")


@dataclass(frozen=True)
class CounterfactualFill:
    fill_id: str
    condition_id: str
    market_id: str
    event_date: date
    minute_utc: datetime
    fill_at_utc: datetime
    maker_side: str
    price: float
    size: float
    context: FillContext
    marks: Mapping[str, Mark]
    settlement_p_yes: float | None
    settlement_observed_at_utc: datetime | None = None
    basis: str = BASIS

    def __post_init__(self):
        utc_time(self.minute_utc)
        utc_time(self.fill_at_utc)
        if self.basis != BASIS:
            raise ToxicityError("non_counterfactual_record")
        if self.maker_side not in ("YES", "NO") or self.maker_side != self.context.maker_side:
            raise ToxicityError("maker_side_mismatch")
        if not (0 < self.price < 1) or not (math.isfinite(self.size) and self.size > 0):
            raise ToxicityError("invalid_fill_price_or_size")
        if not self.minute_utc <= self.fill_at_utc < self.minute_utc + timedelta(minutes=1):
            raise ToxicityError("fill_outside_exposure_minute")
        if self.context.at_utc > self.fill_at_utc:
            raise PointInTimeError("feature timestamped after the fill")
        marks = dict(self.marks)
        for horizon, mark in marks.items():
            if horizon not in HORIZON_SECONDS:
                raise ToxicityError(f"unknown_mark_horizon:{horizon}")
            due = self.fill_at_utc + timedelta(seconds=HORIZON_SECONDS[horizon])
            if not due <= mark.observed_at_utc <= due + MARK_TOLERANCE:
                raise PointInTimeError(f"mark {horizon} not observed at fill + horizon")
        if self.settlement_p_yes is not None and (not math.isfinite(self.settlement_p_yes)
                                                  or not 0 <= self.settlement_p_yes <= 1):
            raise ToxicityError("invalid_settlement")
        if (self.settlement_p_yes is None) != (self.settlement_observed_at_utc is None):
            raise ToxicityError("settlement_needs_observation_time")
        if self.settlement_observed_at_utc is not None:
            utc_time(self.settlement_observed_at_utc)
            if self.settlement_observed_at_utc < self.fill_at_utc:
                raise PointInTimeError("settlement observed before the fill")
        object.__setattr__(self, "marks", MappingProxyType(marks))


def _payload_dates(payload):
    out = [payload.get("event_date"), payload.get("minute_utc"), payload.get("fill_at_utc"),
           payload.get("settlement_observed_at_utc")]
    out += [m.get("observed_at_utc") for m in (payload.get("marks") or {}).values()]
    context = payload.get("context") or {}
    out += [context.get("at_utc"), *(context.get("feature_times") or {}).values()]
    return [v for v in out if v is not None]


def parse_record(payload, *, purpose="read"):
    refuse(*_payload_dates(payload), purpose=purpose)
    if payload.get("basis") != BASIS:
        raise ToxicityError("non_counterfactual_record")
    context = FillContext.from_mapping(payload["context"])
    if payload.get("kind") == "minute":
        return QuoteMinute(payload["condition_id"], payload["market_id"], _day(payload["event_date"]),
                           _time(payload["minute_utc"]), context, payload["basis"])
    if payload.get("kind") == "fill":
        marks = {h: Mark(_time(m["observed_at_utc"]), m["mid_yes"]) for h, m in payload["marks"].items()}
        return CounterfactualFill(payload["fill_id"], payload["condition_id"], payload["market_id"],
                                  _day(payload["event_date"]), _time(payload["minute_utc"]),
                                  _time(payload["fill_at_utc"]), payload["maker_side"], payload["price"],
                                  payload["size"], context, marks, payload["settlement_p_yes"],
                                  None if payload.get("settlement_observed_at_utc") is None
                                  else _time(payload["settlement_observed_at_utc"]), payload["basis"])
    raise ToxicityError("unknown_record_kind")


def read_records(path: Path, *, purpose="read"):
    minutes, fills = [], []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = parse_record(json.loads(line), purpose=purpose)
            (minutes if isinstance(record, QuoteMinute) else fills).append(record)
    return tuple(minutes), tuple(fills)


def check_fit_joins(minutes, fills):
    """The identity checks ``toxicity.fit`` runs before fitting."""
    if not minutes:
        raise ToxicityError("no_counterfactual_minutes")
    exposure = {}
    for m in minutes:
        key = (m.condition_id, m.minute_utc)
        if key in exposure:
            raise ToxicityError("duplicate_quote_minute")
        exposure[key] = m
    seen = set()
    for f in fills:
        if f.fill_id in seen:
            raise ToxicityError("duplicate_fill")
        seen.add(f.fill_id)
        source = exposure.get((f.condition_id, f.minute_utc))
        if source is None:
            raise ToxicityError("fill_without_exposure_minute")
        if (source.market_id, source.event_date) != (f.market_id, f.event_date):
            raise ToxicityError("fill_exposure_identity_mismatch")
        if source.context.maker_side != f.maker_side:
            raise ToxicityError("fill_exposure_side_mismatch")
