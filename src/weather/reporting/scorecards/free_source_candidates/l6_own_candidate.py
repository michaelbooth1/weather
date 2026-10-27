"""Dev-scorecard twin control L6: identical to l6_upstream_candidate but on the OWN-only nowcast (see l6_stack)."""
from weather.reporting.scorecards.free_source_candidates import l6_stack

NAME = "l6_own_stack"


def fit(train):
    return l6_stack.fit(train, "n_own", NAME)


def predict(state, snaps, bands):
    return l6_stack.predict(state, snaps, bands)
