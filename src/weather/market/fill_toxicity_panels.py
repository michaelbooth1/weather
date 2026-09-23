"""Bounded UTC-minute accounting for frozen Clarifications 7 and 8.

Only additive statistics for the current minute are retained. The fill stream
may contain arbitrarily many prints without growing this accumulator.
"""

from collections import defaultdict
import math

from weather.market import execution_tape_markout as base
from weather.market import fill_toxicity_statistics as stats


class MinutePanels:
    def __init__(self, *, midpoint, payoff, end, emit, audit):
        self.midpoint = midpoint
        self.payoff = payoff
        self.end = end
        self.emit = emit
        self.audit = audit
        self.minute = None
        self.horizons = dict(base.HORIZON_SECONDS)
        if payoff is not None:
            self.horizons["settlement"] = None
        self._reset()

    def _reset(self):
        self.parts = defaultdict(stats.zero)
        self.rewards = defaultdict(stats.zero)
        self.active = [False, False]
        self.bad = set()
        self.groups = [set(), set()]

    def advance(self, at):
        minute = math.floor(at / 60) * 60
        if minute != self.minute:
            self.flush()
            self.minute = minute

    def exposure(self, a, b, share_minutes, many, single, groups, population, remaining):
        self.advance(a)
        for group in {"TOTAL", *groups}:
            joint = self.rewards[(population, group)]
            joint["reward_many"] += many
            joint["reward_single"] += single
            for side, size in enumerate(remaining):
                if size <= 0:
                    continue
                self.active[side] = True
                self.groups[side].add(group)
                for adjusted in (False, True):
                    for horizon in self.horizons:
                        self.parts[(adjusted, horizon, side, population, group)]["exposure"] += size * (b - a) / 60

    def fill(self, at, shares, price, side_name, groups, population):
        self.advance(at)
        side = 0 if side_name == "bought" else 1
        self.active[side] = True
        self.groups[side].update({"TOTAL", *groups})
        marks = {}
        for adjusted in (False, True):
            for horizon, seconds in self.horizons.items():
                mark = self.payoff if seconds is None else self.midpoint(at + seconds, adjusted)
                value = base.maker_markout(side_name, price, mark) if mark is not None else None
                marks[("adjusted" if adjusted else "book_mid") + ":" + horizon] = value
                if value is None:
                    self.bad.add((adjusted, horizon, side))
                for group in {"TOTAL", *groups}:
                    part = self.parts[(adjusted, horizon, side, population, group)]
                    part["filled_shares"] += shares
                    part["fills"] += 1
                    if value is not None:
                        part["loss"] += -min(value, 0) * shares
                        part["signed_markout"] += value * shares
                        tail = value < -.05 or math.isclose(value, -.05, rel_tol=0, abs_tol=1e-12)
                        part["tail_shares"] += shares if tail else 0
                        part["tail_fills"] += int(tail)
        return marks

    def flush(self):
        if self.minute is None:
            return
        for adjusted in (False, True):
            for horizon, seconds in self.horizons.items():
                boundaries = seconds is None or all(self.midpoint(at + seconds, adjusted) is not None
                    for at in (self.minute, min(self.end, self.minute + 60)))
                eligible = [active and boundaries and (adjusted, horizon, side) not in self.bad
                            for side, active in enumerate(self.active)]
                removed_fills = defaultdict(float)
                for (adj, h, side, population, group), part in self.parts.items():
                    if (adj, h) != (adjusted, horizon):
                        continue
                    if eligible[side]:
                        self.emit(population, adjusted, horizon, group, part)
                    else:
                        removed_fills[group] += part["fills"]
                counts = {group: sum(self.active[side] and not eligible[side] and group in self.groups[side]
                                    for side in (0, 1)) for group in set.union(*self.groups)}
                if any(counts.values()):
                    self.audit({"type": "removed_leg_minutes", "minute": self.minute,
                        "midpoint": "adjusted" if adjusted else "book_mid", "horizon": horizon,
                        "leg_minutes_by_group": counts, "fills_by_group": dict(removed_fills)})
                if horizon == "30m":
                    # Preserve the original joint reward. No allocation to a leg
                    # and no counterfactual single-leg reward calculation.
                    if all(eligible):
                        keys = set(self.rewards) | {(p, g) for adj, h, side, p, g in self.parts
                                                   if adj == adjusted and h == horizon}
                        for population, group in keys:
                            value = dict(self.rewards[(population, group)])
                            value["net_loss"] = sum(self.parts[(adjusted, horizon, side, population, group)]["loss"]
                                                    for side in (0, 1))
                            self.emit(population, adjusted, horizon, group, value)
                    elif any(self.active):
                        self.audit({"type": "removed_quote_minutes", "minute": self.minute,
                            "midpoint": "adjusted" if adjusted else "book_mid", "horizon": "30m",
                            "quote_minutes_by_group": {group: 1 for group in set.union(*self.groups)}})
        self._reset()
