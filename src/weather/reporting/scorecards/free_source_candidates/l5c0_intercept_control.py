"""L5 AFD matched control: coastal per-market intercepts only, no AFD (see l5c_afd_common)."""
from weather.reporting.scorecards.free_source_candidates import l5c_afd_common as A

NAME = "l5c0_coastal_intercepts"


def fit(train):
    return A.fit(train, False, NAME)


def predict(state, snaps, bands):
    return A.predict(state, snaps, bands, False)
