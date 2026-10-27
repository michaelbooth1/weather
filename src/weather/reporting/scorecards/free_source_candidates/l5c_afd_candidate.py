"""L5 AFD candidate: coastal per-market intercepts plus AFD text features (see l5c_afd_common)."""
from weather.reporting.scorecards.free_source_candidates import l5c_afd_common as A

NAME = "l5c_afd_features"


def fit(train):
    return A.fit(train, True, NAME)


def predict(state, snaps, bands):
    return A.predict(state, snaps, bands, True)
