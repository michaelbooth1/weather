"""Dev-scorecard candidate L6: MG-1 recentred on the OWN + UPSTREAM observation nowcast (see l6_stack)."""
from weather.reporting.scorecards.free_source_candidates import l6_stack

NAME = "l6_upstream_stack"


def fit(train):
    return l6_stack.fit(train, "n_up", NAME)


def predict(state, snaps, bands):
    return l6_stack.predict(state, snaps, bands)
