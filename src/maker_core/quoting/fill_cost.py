"""Injected fill-cost (adverse-selection) provider for the informed-maker net screen.

Item 330 build 2. Pure kernel: no IO, no venue, no domain imports. Nothing in
``policy.py`` imports this module yet; wiring it in is a separate, later,
roll-sensitive change. Until then a caller may apply it *around* ``decide()``
with :func:`apply_fill_cost` / :func:`decide_with_fill_cost`.

What the provider returns is **COUNTERFACTUAL**: a table fitted by
``maker_core.replay.toxicity`` on hypothetical resting quotes matched to public
prints (price-path markouts, EF §1b/§8c). It is not our fills and it is not the
informed-fill fraction. Its numbers are an upper-bound envelope that can only
make the screen stricter than today's constant:

- ``CONSTANT_ADVERSE_MARKOUT`` = 0.0043 probability per share (the public-tape
  -0.43 c settlement markout, item 330, 2026-09-20) stays the floor;
- the caller's hazard bound stays a floor;
- a burst or a cross-band sweep in the trailing window is a veto.

When the provider is ``Unavailable`` the decision inputs are returned unchanged,
which is exactly today's constant path (differential test).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
import math
from types import MappingProxyType
from typing import Mapping, Protocol, runtime_checkable

from maker_core.contracts import Unavailable, utc_time
from maker_core.contracts.evidence_embargo import refuse as refuse_embargo
from maker_core.evidence.journal import digest
from maker_core.quoting import policy as _policy

CONSTANT_ADVERSE_MARKOUT = 0.0043  # Probability units per share; equals DecisionInputs' default.
TABLE_VERSION = "maker_core.toxicity_table.v0.1"
LABEL = "COUNTERFACTUAL"
HORIZONS = ("1m", "5m", "30m", "settlement")
HORIZON_SECONDS = {"1m": 60, "5m": 300, "30m": 1800}
FEATURE_GROUPS = ("info_clock", "decided", "book", "prints")
DIMENSIONS = ("clock", "decided", "close", "horizon", "imbalance", "depth", "print", "flow")


class PointInTimeError(ValueError):
    """A feature or label is timestamped after the instant it describes."""


@dataclass(frozen=True)
class TableSpec:
    """Bucket edges and flow thresholds. Declared constants, not fitted parameters.

    Sweep: 94a found a same-event band traded within 60 s after another 52% of
    the time, so two bands is ordinary flow; a sweep needs ``sweep_min_bands``.
    """
    print_window_before_min: float = 3.0   # policy pulls -3/+10 min around a scheduled print
    print_window_after_min: float = 10.0
    model_cycle_fresh_min: float = 60.0
    decided_edges: tuple[float, float] = (0.2, 0.5)
    close_edges_min: tuple[float, float] = (360.0, 1440.0)
    imbalance_edge: float = 1 / 3
    thin_depth_shares: float = 75.0
    large_print_shares: float = 100.0
    burst_window_s: float = 1.0
    burst_min_prints: int = 5
    sweep_window_s: float = 60.0
    sweep_min_bands: int = 3
    min_fills_per_row: int = 30

    def as_dict(self):
        return {k: (list(v) if isinstance(v, tuple) else v) for k, v in asdict(self).items()}

    @classmethod
    def from_dict(cls, payload: Mapping):
        values = {k: (tuple(v) if isinstance(v, list) else v) for k, v in dict(payload).items()}
        spec = cls(**values)
        if spec.as_dict() != dict(payload):
            raise ValueError("toxicity spec does not round-trip")
        return spec


DEFAULT_SPEC = TableSpec()


def _finite(value, name, low=None, high=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    if (low is not None and value < low) or (high is not None and value > high):
        raise ValueError(f"{name} out of range")


@dataclass(frozen=True)
class FillContext:
    """Point-in-time context of one band at ``at_utc`` (trailing data only).

    ``feature_times`` names the newest input time behind each feature group;
    every one must be at or before ``at_utc``, and ``prints`` strictly before it
    (the print at the fill instant is the fill itself). Market prices enter only the
    ``book``/``prints`` groups (flow state), never ``decided`` or ``info_clock``.
    """
    at_utc: datetime
    maker_side: str                       # token the resting maker leg buys: YES or NO
    horizon_days: int
    minutes_to_close: float
    minutes_from_scheduled_print: float | None   # signed; negative before the print
    minutes_since_model_cycle: float | None
    decided_probability: float | None
    book_imbalance: float | None          # YES axis: (bid - ask) / (bid + ask) depth
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
    def from_mapping(cls, payload: Mapping):
        values = dict(payload)
        values["at_utc"] = _parse_time(values["at_utc"])
        values["feature_times"] = {k: _parse_time(v) for k, v in dict(values.get("feature_times") or {}).items()}
        return cls(**values)

    def as_dict(self):
        out = {f: getattr(self, f) for f in self.__dataclass_fields__}
        out["at_utc"] = self.at_utc.isoformat()
        out["feature_times"] = {k: v.isoformat() for k, v in sorted(self.feature_times.items())}
        return out


def _parse_time(value):
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def flow_state(context: FillContext, spec: TableSpec = DEFAULT_SPEC) -> str:
    if context.sweep_bands >= spec.sweep_min_bands:
        return "sweep"
    if context.burst_prints >= spec.burst_min_prints:
        return "burst"
    return "calm"


def levels(context: FillContext, spec: TableSpec = DEFAULT_SPEC) -> dict[str, str]:
    """One bucket label per dimension, in ``DIMENSIONS`` order."""
    p = context.minutes_from_scheduled_print
    if p is not None and -spec.print_window_before_min <= p <= spec.print_window_after_min:
        clock = "print_window"
    elif context.minutes_since_model_cycle is not None and context.minutes_since_model_cycle < spec.model_cycle_fresh_min:
        clock = "model_cycle"
    elif p is None and context.minutes_since_model_cycle is None:
        clock = "unknown"
    else:
        clock = "quiet"
    d = context.decided_probability
    decided = ("unknown" if d is None else "low" if d < spec.decided_edges[0]
               else "mid" if d < spec.decided_edges[1] else "high")
    m = context.minutes_to_close
    close = "lt6h" if m < spec.close_edges_min[0] else "6to24h" if m < spec.close_edges_min[1] else "gt24h"
    horizon = "T+0" if context.horizon_days == 0 else "T+1" if context.horizon_days == 1 else "T+2+"
    if context.book_imbalance is None:
        imbalance = "unknown"
    else:
        # Signed toward the maker: a YES bid is threatened by ask-heavy (negative) books.
        aligned = context.book_imbalance * (1 if context.maker_side == "YES" else -1)
        imbalance = ("against" if aligned < -spec.imbalance_edge
                     else "with" if aligned > spec.imbalance_edge else "balanced")
    depth = "thin" if context.depth_shares < spec.thin_depth_shares else "deep"
    size = context.last_print_size
    print_ = "none" if size == 0 else "large" if size >= spec.large_print_shares else "small"
    return dict(zip(DIMENSIONS, (clock, decided, close, horizon, imbalance, depth, print_,
                                 flow_state(context, spec))))


@dataclass(frozen=True)
class FillCostEstimate:
    """COUNTERFACTUAL upper-bound envelope for one band context.

    ``hazard_per_minute_upper`` is None when the table cannot support a hazard
    bound; the caller's bound then stands. ``adverse_markout_upper`` is a loss in
    probability units per share and is never below the constant floor.
    """
    hazard_per_minute_upper: float | None
    adverse_markout_upper: float
    veto: str | None
    status: str
    table_digest: str
    rows: tuple[str, ...]
    label: str = LABEL

    def __post_init__(self):
        if self.label != LABEL:
            raise ValueError("fill-cost estimates are counterfactual")
        if self.hazard_per_minute_upper is not None:
            _finite(self.hazard_per_minute_upper, "hazard", 0, 1)
        _finite(self.adverse_markout_upper, "adverse markout", CONSTANT_ADVERSE_MARKOUT)
        if self.veto not in (None, "BURST", "SWEEP"):
            raise ValueError("unknown veto")


@runtime_checkable
class FillCostProvider(Protocol):
    def estimate(self, context: FillContext) -> FillCostEstimate | Unavailable: ...


class ConstantFillCost:
    """Today's path: no table, always Unavailable, so the constant stands."""

    def estimate(self, context: FillContext) -> Unavailable:
        return Unavailable("no fitted counterfactual fill-cost table", context.at_utc)


def validate_table(table: Mapping) -> TableSpec:
    if table.get("table_version") != TABLE_VERSION:
        raise ValueError("unknown toxicity table version")
    if table.get("label") != LABEL:
        raise ValueError("toxicity table must be labelled COUNTERFACTUAL")
    spec = TableSpec.from_dict(table["spec"])
    if table.get("spec_digest") != digest(spec.as_dict()):
        raise ValueError("toxicity spec digest mismatch")
    if spec != DEFAULT_SPEC:
        # TABLE_VERSION pins the declared bucket edges; another spec needs a new version.
        raise ValueError(f"{TABLE_VERSION} requires the default spec")
    if tuple(table.get("horizons", ())) != HORIZONS:
        raise ValueError("toxicity horizons mismatch")
    last = table.get("fit_window", {}).get("last_date")
    if last is None:
        raise ValueError("toxicity table has no fit window")
    refuse_embargo(last, purpose="fit")
    return spec


class TableFillCostProvider:
    """Reads a fitted COUNTERFACTUAL table (plain mapping) and returns an envelope.

    Envelope = max over the pooled row and every matching one-way row with at
    least ``min_fills_per_row`` fills of the stored one-sided upper bounds (the
    upper end of the crossed date x market 90% interval). Rows below support are
    skipped; if the pooled row is below support the table is Unavailable unless
    a burst/sweep veto applies.
    """

    def __init__(self, table: Mapping):
        self.spec = validate_table(table)
        self.table = table
        self.digest = digest(table)
        self.rows = {(r["dimension"], r["level"]): r for r in table["rows"]}
        if ("pooled", "all") not in self.rows:
            raise ValueError("toxicity table lacks a pooled row")

    def _supported(self, cell):
        return cell["fills"] >= self.spec.min_fills_per_row

    def estimate(self, context: FillContext) -> FillCostEstimate | Unavailable:
        refuse_embargo(context.at_utc, *context.feature_times.values(), purpose="read")
        labels = levels(context, self.spec)
        flow = labels["flow"]
        veto = {"sweep": "SWEEP", "burst": "BURST"}.get(flow)
        keys = [("pooled", "all")] + [(d, labels[d]) for d in DIMENSIONS]
        if not self._supported(self.rows[("pooled", "all")]):
            if veto is None:
                return Unavailable("counterfactual table below support", context.at_utc)
            return FillCostEstimate(None, CONSTANT_ADVERSE_MARKOUT, veto, "UNSUPPORTED", self.digest, ())
        # Hazard cells are keyed by the exposure minute's context and markout cells by the fill
        # instant's context, so each cell is gated on its own fill count.
        hazards, losses, statuses, used = [], [CONSTANT_ADVERSE_MARKOUT], set(), []
        for key in keys:
            row = self.rows.get(key)
            if row is None:
                continue
            contributed = False
            if self._supported(row) and row["hazard"]["interval"]:
                hazards.append(min(1.0, max(0.0, row["hazard"]["interval"][1])))
                statuses.add(row["hazard"]["status"])
                contributed = True
            for h in HORIZONS:
                cell = row["markout"][h]
                if self._supported(cell) and cell["interval"]:
                    losses.append(-cell["interval"][0])  # loss upper = -(markout lower)
                    statuses.add(cell["status"])
                    contributed = True
            if contributed:
                used.append(f"{key[0]}={key[1]}")
        status = "OK" if statuses <= {"OK"} else "UNDERPOWERED"
        return FillCostEstimate(max(hazards) if hazards else None, max(losses), veto, status,
                                self.digest, tuple(used))


@dataclass(frozen=True)
class PolicyFillInputs:
    hazard_per_minute: float | None
    adverse_markout: float
    veto: str | None
    source: str        # constant_fallback | counterfactual_table
    status: str


def policy_fill_inputs(result, *, caller_hazard: float | None,
                       caller_markout: float = CONSTANT_ADVERSE_MARKOUT) -> PolicyFillInputs:
    """Map a provider result onto the two ``DecisionInputs`` fields and a veto.

    ``Unavailable`` returns the caller's own values untouched (today's path).
    An estimate can only raise an existing bound: hazard = max(caller, table) and
    markout = max(caller, constant, table). A missing (None) or non-finite caller
    hazard is kept as is, so the policy's MISSING_CONSERVATIVE_FILL_BOUND refusal
    still fires; the table never supplies a hazard the caller did not have.
    """
    if isinstance(result, Unavailable):
        return PolicyFillInputs(caller_hazard, caller_markout, None, "constant_fallback", "UNAVAILABLE")
    if not isinstance(result, FillCostEstimate):
        raise TypeError("provider must return FillCostEstimate or Unavailable")
    hazard = caller_hazard
    if (result.hazard_per_minute_upper is not None and caller_hazard is not None
            and math.isfinite(caller_hazard)):
        hazard = max(caller_hazard, result.hazard_per_minute_upper)
    markout = max(caller_markout, CONSTANT_ADVERSE_MARKOUT, result.adverse_markout_upper)
    return PolicyFillInputs(hazard, markout, result.veto, "counterfactual_table", result.status)


def apply_fill_cost(inputs, provider: FillCostProvider, context: FillContext):
    """Return ``(DecisionInputs, PolicyFillInputs)``; the inputs are unchanged on Unavailable."""
    if context.at_utc > inputs.now:
        raise PointInTimeError("fill context is after the decision instant")
    mapped = policy_fill_inputs(provider.estimate(context), caller_hazard=inputs.hazard_per_minute,
                                caller_markout=inputs.adverse_markout)
    if mapped.source == "constant_fallback":
        return inputs, mapped
    return replace(inputs, hazard_per_minute=mapped.hazard_per_minute,
                   adverse_markout=mapped.adverse_markout), mapped


VETO_ACTIONS = ("cancel", "widen")


def _withdraw(decision, inputs, veto):
    return replace(decision, action="CANCEL" if inputs.existing else "NO_QUOTE", legs=(),
                   reasons=(f"FILL_COST_VETO_{veto}",), share_many=0.0, net_per_minute=0.0)


def _widen(decision, inputs, veto, widen_ticks):
    """Move every resting buy leg ``widen_ticks`` ticks further from fair; drop legs that leave the book.

    A widened leg may fall outside the reward band (it then earns no share); the
    reported share and net are zeroed rather than re-estimated, so the widen path
    can never look better than the policy's own estimate.
    """
    tick = inputs.market.tick
    legs = tuple(replace(leg, price=leg.price - tick * widen_ticks) for leg in decision.legs
                 if leg.price - tick * widen_ticks >= tick)
    if not legs:
        return _withdraw(decision, inputs, veto)
    # A widened HOLD is a requote at the new prices.
    return replace(decision, action="QUOTE", legs=legs,
                   reasons=(*decision.reasons, f"FILL_COST_VETO_{veto}_WIDENED"),
                   share_many=0.0, net_per_minute=0.0)


def decide_with_fill_cost(inputs, provider: FillCostProvider, context: FillContext, decide=None, *,
                          veto_action: str = "cancel", widen_ticks: int = 2):
    """Adapter a later policy change could adopt.

    On a burst/sweep veto a QUOTE/HOLD is withdrawn (``veto_action="cancel"``, the
    conservative default) or widened by ``widen_ticks`` ticks (``"widen"``). Which one
    policy adopts is decided at wiring time, with evidence.
    """
    if veto_action not in VETO_ACTIONS:
        raise ValueError("veto_action must be cancel or widen")
    if type(widen_ticks) is not int or widen_ticks < 1:
        raise ValueError("widen_ticks must be a positive int")
    decide = decide or _policy.decide
    adjusted, mapped = apply_fill_cost(inputs, provider, context)
    decision = decide(adjusted)
    if mapped.veto and decision.action in ("QUOTE", "HOLD"):
        if veto_action == "widen":
            return _widen(decision, inputs, mapped.veto, widen_ticks)
        return _withdraw(decision, inputs, mapped.veto)
    return decision
