"""Injection seams for builds 1 and 2 of item 330 (fill v3 and the toxicity fill cost).

The frontier runner depends only on the two protocols here. Each has a stand-in that reproduces today's
behaviour. When build 1 or build 2 lands, its object is passed in; this package does not change.

``FillModel``
    ``place(legs, book)`` returns opaque resting state. ``on_trade(state, trade)`` returns
    ``(state, ((leg, filled_size), ...))``.

    - ``PricePathFillModel`` is the stand-in. It wraps the frozen v2 ``fill_model.match`` under either
      89a bound and ignores queue position.
    - ``QueueFillModel`` is the adapter for build 1. It takes the fill-v3 kernel (anything exposing
      ``eligibility(leg, trade)``, ``q_ahead(book, leg)`` and ``QueueState(size, queue)``) by injection,
      so nothing here imports an unlanded module.

``FillCostProvider``
    ``estimate(context)`` returns an object with ``adverse_markout_upper`` and ``veto``, or anything else
    to mean unavailable. This is duck-typed to build 2's ``FillCostEstimate`` / ``Unavailable``.

    - ``ConstantFillCost`` is the stand-in and is always unavailable.
    - ``fill_cost_terms`` turns an estimate into ``(markout, veto)``. The markout never falls below the
      constant 0.0043 (the public-tape settlement markout), so a provider can only make the cost stricter.
    - ``context_builder`` (a runner argument) builds the provider's context. Its default returns None.

Fill-model binding (``binding``)
    A preregistration binds the fill model by ``binding(model)``, never by ``.name`` alone, because a name is
    a free constructor argument (``QueueFillModel(kernel, name="v2-strictly_through")`` would otherwise pass
    as the v2 model). The binding is ``<module>.<qualname>@<version>:<name>``:

    - only the exact classes in ``REGISTERED_FILL_MODELS`` bind (a subclass or any other class gets an
      ``unregistered:`` binding that a scored run refuses);
    - the version is the class's ``VERSION`` constant; a ``QueueFillModel`` appends its kernel's module name
      and ``VERSION`` (``unversioned`` when the kernel has none, which a scored run also refuses);
    - a name that contradicts its class (a ``QueueFillModel`` not named ``v3-...``, a ``PricePathFillModel``
      whose name is not ``v2-<bound>``) is refused outright (``FillBindingRefused``).
"""
from __future__ import annotations

from decimal import Decimal
import math
from typing import Protocol, runtime_checkable

from maker_core.replay.fill_model import BOUNDS, match

CONSTANT_ADVERSE_MARKOUT = 0.0043
VETOES = (None, "BURST", "SWEEP")
UNREGISTERED = "unregistered:"
UNVERSIONED = "unversioned"


class FillBindingRefused(ValueError):
    """A fill model's name contradicts its class."""


@runtime_checkable
class FillModel(Protocol):
    name: str

    def place(self, legs, book): ...

    def on_trade(self, state, trade): ...


class PricePathFillModel:
    """Stand-in: the frozen v2 price-path predicate, one bound per instance."""

    VERSION = "v2-price-path.1"

    def __init__(self, bound: str = "strictly_through"):
        if bound not in BOUNDS:
            raise ValueError("unknown fill bound")
        self.bound, self.name = bound, "v2-" + bound

    def place(self, legs, book):
        return {"legs": tuple(legs), "left": {i: leg.size for i, leg in enumerate(legs)}}

    def on_trade(self, state, trade):
        live = tuple(leg for i, leg in enumerate(state["legs"]) if state["left"][i] > 0)
        hit = match(live, trade, self.bound) if live else None
        if hit is None:
            return state, ()
        leg, size = hit
        index = state["legs"].index(leg)
        size = min(size, state["left"][index])
        left = dict(state["left"])
        left[index] -= size
        return dict(state, left=left), ((leg, size),)


class QueueFillModel:
    """Adapter for build 1: a queue-aware fill through an injected fill-v3 kernel."""

    VERSION = "queue-adapter.1"

    def __init__(self, kernel, name: str = "v3-queue"):
        for attribute in ("eligibility", "q_ahead", "QueueState"):
            if not hasattr(kernel, attribute):
                raise TypeError("fill kernel lacks " + attribute)
        self.kernel, self.name = kernel, name

    def place(self, legs, book):
        queues = []
        for leg in legs:
            ahead = self.kernel.q_ahead(book, leg)
            queues.append(self.kernel.QueueState(leg.size, Decimal(0) if ahead is None else ahead))
        return {"legs": tuple(legs), "queues": tuple(queues), "left": {i: leg.size for i, leg in enumerate(legs)}}

    def on_trade(self, state, trade):
        fills, left = [], dict(state["left"])
        for i, leg in enumerate(state["legs"]):
            if left[i] <= 0 or self.kernel.eligibility(leg, trade) is None:
                continue
            size = min(state["queues"][i].consume(trade.size), left[i])
            if size > 0:
                left[i] -= size
                fills.append((leg, size))
                break  # one print fills at most one of our legs, as in v2
        return dict(state, left=left), tuple(fills)


REGISTERED_FILL_MODELS = (PricePathFillModel, QueueFillModel)


def _qualified(cls) -> str:
    return cls.__module__ + "." + cls.__qualname__


def binding(model) -> str:
    """The identity a preregistration binds: exact class, version constant(s) and name; see the module doc."""
    cls, name = type(model), getattr(model, "name", None)
    if not isinstance(name, str) or not name or any(c.isspace() or c == "`" for c in name):
        raise FillBindingRefused("fill_model_name_invalid")
    if cls not in REGISTERED_FILL_MODELS:
        return UNREGISTERED + _qualified(cls) + ":" + name
    if cls is PricePathFillModel:
        if name != "v2-" + model.bound:
            raise FillBindingRefused("fill_model_name_contradicts_class")
        version = cls.VERSION
    else:
        if not name.startswith("v3-"):
            raise FillBindingRefused("fill_model_name_contradicts_class")
        kernel = model.kernel
        kernel_name = getattr(kernel, "__name__", None) or _qualified(type(kernel))
        kernel_version = getattr(kernel, "VERSION", None)
        if not isinstance(kernel_version, str) or not kernel_version:
            kernel_version = UNVERSIONED
        version = "%s+%s@%s" % (cls.VERSION, kernel_name, kernel_version)
    return "%s@%s:%s" % (_qualified(cls), version, name)


def is_bindable(value: str) -> bool:
    """True when a binding may be signed: a registered class and a versioned kernel."""
    return not value.startswith(UNREGISTERED) and "@" + UNVERSIONED + ":" not in value


@runtime_checkable
class FillCostProvider(Protocol):
    def estimate(self, context): ...


class ConstantFillCost:
    """Stand-in: always unavailable, so the constant markout applies (today's path)."""

    def estimate(self, context):
        return None


def fill_cost_terms(estimate) -> tuple[float, str | None]:
    """(markout per filled share, veto) from a provider result; unavailable means (0.0043, None)."""
    markout = getattr(estimate, "adverse_markout_upper", None)
    veto = getattr(estimate, "veto", None)
    if markout is None:
        return CONSTANT_ADVERSE_MARKOUT, None
    markout = float(markout)
    if not math.isfinite(markout):
        raise ValueError("nonfinite_markout")
    if veto not in VETOES:
        raise ValueError("unknown_veto")
    return max(markout, CONSTANT_ADVERSE_MARKOUT), veto


def no_context(**_):
    return None
