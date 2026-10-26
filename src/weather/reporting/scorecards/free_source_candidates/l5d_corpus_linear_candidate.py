"""L5 arm B1: per-market linear centre on the gfs day-1 high, fitted on the full-year 2021-25 corpus."""
from weather.reporting.scorecards.free_source_candidates import l5_centre as C, l5_corpus as K

NAME = "l5d_corpus_linear_fullyear"


def fit(train):
    st = K.fit_coefs(None)
    st["provenance"]["rule"] = NAME
    return st


def predict(state, snaps, bands):
    s = snaps.reset_index(drop=True)
    return C.serve(s, bands, K.corpus_mu(state, s))
