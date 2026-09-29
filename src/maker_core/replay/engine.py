"""Closed-bundle replay composition; the RE-1 adapter stays outside shadow."""
from maker_core.replay.lifecycle import (
    D, EPSILON, ReplayConfig, DecisionEvent, Span, State, ReplayResult, Lifecycle,
)
from maker_core.replay.re1_counterfactual import tick as blind_tick


class ReplayEngine(Lifecycle):
    def blind_tick(self, cid, at, value):
        blind_tick(self, cid, at, value)


def replay(bundles, config=ReplayConfig(), *, check=lambda: None):
    return ReplayEngine(tuple(bundles), config, check=check).run()
