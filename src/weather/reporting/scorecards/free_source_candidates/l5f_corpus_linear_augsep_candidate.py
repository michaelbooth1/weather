"""L5 arm B sensitivity (reported only): arm B1 fitted on Aug-Sep 2021-25 pairs only (in-season coverage)."""
from weather.reporting.scorecards.free_source_candidates import l5_centre as C, l5_corpus as K

NAME = "l5f_corpus_linear_augsep"


def fit(train):
    st = K.fit_coefs([8, 9])
    st["provenance"]["rule"] = NAME
    return st


def predict(state, snaps, bands):
    s = snaps.reset_index(drop=True)
    return C.serve(s, bands, K.corpus_mu(state, s))
