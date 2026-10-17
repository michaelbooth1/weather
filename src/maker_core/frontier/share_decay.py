"""Competitor-response (reward-share decay) model for the informed-v1 frontier (item 330 build 3).

Replay reads historical books on which we never rested. When we quote, other makers add or move size, so a
replayed share that ignores their reaction is an upper bound. The model represents that reaction as extra
competing Q, measured in units of our own Q, as a function of how long our quote has been up:

    x(a) = (C(a) - C0) / own(a)           measured: C0 is competing Q at selection, before we posted
    x(a) = k * (1 - exp(-a / tau))         fitted, with a in minutes since we opened
    share(a) = own / (own + C_hist(a) + x(a) * own)

``C_hist`` is competing Q in the replayed book. There are three bounds:

- ``none``: x = 0, no reaction, the optimistic replay share;
- ``central``: the median of per-session fits (k, tau), each a grid least-squares fit in share space;
- ``full``: x = the largest fitted plateau k among identified sessions, applied from a = 0.

Units: x and k are extra competing Q per unit of our own Q (dimensionless). With no historical competition,
the full bound caps our share at 1 / (1 + x_full).

A session fit whose tau lands on an edge of ``TAU_GRID_MINUTES`` is not identified (``tau_at_bound``). It is
kept and disclosed in ``fits`` but excluded from the central medians and the full bound. The raw largest
observed reaction (``x_max``) stays in each session fit as a diagnostic. It is not used as the full bound,
because late in a session our quote can drift off mid, so own Q falls while the book grows, and the ratio
then measures drift, not competitor reaction. The full bound is reported beside the central fit; it never
decides anything on its own.

Fits use only dates on or before 2026-09-29 (``embargo.check("fit", ...)``). The source is the RE-1
decision projection (``re1_sessions``). A depth series in the same ``Session`` shape (for example, from 88a
captures) fits through ``fit`` unchanged. The numbers are descriptive: twelve attempts in one week are not
a calibrated estimate.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import math
import statistics
from typing import Mapping, Sequence

from maker_core.evidence.journal import digest
from maker_core.frontier.embargo import check
from maker_core.quoting.rewards import order_score, q_min, share_of, side_score

BOUNDS = ("none", "central", "full")
TAU_GRID_MINUTES = (0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 7.5, 10.0, 15.0, 20.0, 30.0, 45.0, 60.0)
K_GRID = (0.0,) + tuple(round(0.01 * 10 ** (i / 30), 6) for i in range(121))  # 0, 0.01..100
MIN_SAMPLES = 3


@dataclass(frozen=True)
class Sample:
    at: datetime
    competing: float  # competing Q in the book, with our own resting size removed
    own: float        # our own Q at our resting prices


@dataclass(frozen=True)
class Session:
    label: str
    opened_at: datetime
    own0: float        # our Q at selection
    competing0: float  # competing Q at selection, before we posted
    samples: tuple[Sample, ...]

    def ages(self):
        return tuple((s.at - self.opened_at).total_seconds() / 60 for s in self.samples)

    def reaction(self):
        """(age_minutes, x) for each sample with positive own Q."""
        return tuple((a, (s.competing - self.competing0) / s.own)
                     for a, s in zip(self.ages(), self.samples) if s.own > 0)

    def share0(self):
        return share_of(self.own0, self.competing0)

    def shares(self):
        return tuple((a, share_of(s.own, s.competing)) for a, s in zip(self.ages(), self.samples))

    def halving_minutes(self):
        """First age at which the observed share is at most half the selection share; None if never."""
        half = self.share0() / 2
        return next((a for a, value in self.shares() if value <= half), None)


@dataclass(frozen=True)
class SessionFit:
    label: str
    samples: int
    k: float | None
    tau_minutes: float | None
    rmse: float | None
    x_max: float | None
    share0: float
    halving_minutes: float | None
    tau_at_bound: bool = False  # tau on an edge of TAU_GRID_MINUTES: not identified, excluded from medians


@dataclass(frozen=True)
class DecayModel:
    k: float
    tau_minutes: float
    x_full: float
    fits: tuple[SessionFit, ...]

    def extra(self, bound: str, age_minutes: float) -> float:
        if bound not in BOUNDS:
            raise ValueError("unknown_decay_bound")
        if bound == "none":
            return 0.0
        if bound == "full":
            return self.x_full
        return self.k * (1 - math.exp(-max(age_minutes, 0.0) / self.tau_minutes))

    def share(self, bound: str, own: float, competing: float, age_minutes: float) -> float:
        if own <= 0:
            return 0.0
        return own / (own + max(competing, 0.0) + self.extra(bound, age_minutes) * own)

    def halving_minutes(self, bound: str, share0: float, horizon_minutes: float = 120.0):
        """First tenth-minute at which a quote opened at ``share0`` holds at most half of it; None if never."""
        if not 0 < share0 <= 1:
            raise ValueError("share0_out_of_range")
        competing = 1 / share0 - 1
        steps = int(horizon_minutes * 10)
        return next((n / 10 for n in range(steps + 1)
                     if self.share(bound, 1.0, competing, n / 10) <= share0 / 2), None)

    def summary(self):
        return {"k": self.k, "tau_minutes": self.tau_minutes, "x_full": self.x_full,
                "sessions": [f.__dict__ for f in self.fits]}

    def digest(self):
        return digest(self.summary())


def fit_session(session: Session) -> SessionFit:
    """Grid least squares in share space: reward is linear in share, so share errors are what matter."""
    points = [(a, s) for a, s in zip(session.ages(), session.samples) if s.own > 0]
    x_max = max((x for _, x in session.reaction()), default=None)
    if len(points) < MIN_SAMPLES:
        return SessionFit(session.label, len(points), None, None, None, x_max, session.share0(),
                          session.halving_minutes())
    observed = [share_of(s.own, s.competing) for _, s in points]
    best = None
    for tau in TAU_GRID_MINUTES:  # grid order breaks ties toward the faster reaction, then the smaller k
        basis = [1 - math.exp(-a / tau) for a, _ in points]
        for k in K_GRID:
            sse = sum((o - s.own / (s.own + session.competing0 + k * f * s.own)) ** 2
                      for o, f, (_, s) in zip(observed, basis, points))
            if best is None or sse < best[0]:
                best = (sse, k, tau)
    sse, k, tau = best
    at_bound = tau in (TAU_GRID_MINUTES[0], TAU_GRID_MINUTES[-1])
    # rmse is the absolute root-mean-square error in share (0..1), not a relative error
    return SessionFit(session.label, len(points), k, tau, math.sqrt(sse / len(points)), x_max,
                      session.share0(), session.halving_minutes(), at_bound)


def fit(sessions: Sequence[Session], *, purpose: str = "fit") -> DecayModel:
    """Embargo-checked fit. Central is the median over identified sessions; full is their largest k."""
    if purpose != "fit":
        raise ValueError("decay_fit_purpose_must_be_fit")
    for session in sessions:
        check("fit", session.opened_at, *(s.at for s in session.samples))
    fits = tuple(fit_session(s) for s in sessions)
    fitted = [f for f in fits if f.k is not None and not f.tau_at_bound]
    if not fitted:
        raise ValueError("no_session_with_enough_samples")
    k = statistics.median(f.k for f in fitted)
    tau = statistics.median(f.tau_minutes for f in fitted)
    x_full = max(f.k for f in fitted)
    return DecayModel(k, tau, x_full, fits)


# -- RE-1 decision projection adapter -------------------------------------------------------------------
def _levels(rows):
    out = {}
    for row in rows:
        price, size = (row["price"], row["size"]) if isinstance(row, Mapping) else row
        price, size = Decimal(str(price)), Decimal(str(size))
        out[price] = out.get(price, Decimal(0)) + size
    return out


def _q(inputs, prices, size, own_in_book):
    """(own Q, competing Q) with the RE-1 kernels; own size is removed at our prices when it rests."""
    minimum, spread = Decimal(str(inputs["reward_min_size"])), Decimal(str(inputs["reward_max_spread_cents"]))
    yes_bids, yes_asks = _levels(inputs["yes_bids"]), _levels(inputs["yes_asks"])
    bids = [p for p, s in yes_bids.items() if s >= minimum]
    asks = [p for p, s in yes_asks.items() if s >= minimum]
    if not bids or not asks or max(bids) >= min(asks):
        raise ValueError("no_qualified_mid")
    mid = (max(bids) + min(asks)) / 2
    yes, no = prices
    scores = []
    for levels, own_price in ((yes_bids, yes), (yes_asks, 1 - no)):
        if own_in_book:
            levels = dict(levels)
            levels[own_price] = max(Decimal(0), levels.get(own_price, Decimal(0)) - size)
        scores.append(side_score([(float(p), float(s)) for p, s in levels.items() if s > 0], float(mid),
                                 float(spread), float(minimum))[0])
    own = q_min(*(order_score(float(size), float(d), float(spread), float(minimum))
                  for d in ((mid - yes) * 100, (1 - mid - no) * 100)), float(mid))
    return own, sum(scores) / 2


def re1_sessions(projection: Mapping, selections: Sequence[Mapping], *, purpose: str = "fit"):
    """Sessions from the identity-free RE-1 projection and its selection parity rows (dated read)."""
    by_attempt = {row["attempt"]: row for row in selections}
    out = []
    for raw in projection["sessions"]:
        opened = datetime.fromisoformat(raw["opening"]["at"])
        minutes = raw.get("minutes") or ()
        check(purpose, opened, *(datetime.fromisoformat(m["observed_at"]) for m in minutes))
        selection = by_attempt.get(raw["attempt"])
        if not minutes or selection is None:
            continue
        size = Decimal(str(raw["size"]))
        own0, competing0 = _q(selection["quote_inputs"],
                              [Decimal(str(p)) for p in selection["expected_prices"]], size, False)
        samples = []
        for minute in minutes:
            own, competing = _q(minute["quote_inputs"], [Decimal(str(p)) for p in minute["prices"]], size, True)
            samples.append(Sample(datetime.fromisoformat(minute["observed_at"]), competing, own))
        out.append(Session("attempt-%d" % raw["attempt"], opened, own0, competing0, tuple(samples)))
    return tuple(out)
