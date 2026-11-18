"""L5 arm B2: mu = (v2_mean + arm-B1 corpus centre) / 2 inside 07-12 (fixed 50/50, as lane G's F4)."""
import numpy as np

from weather.reporting.scorecards.free_source_candidates import l5_centre as C, l5_corpus as K

NAME = "l5e_corpus_half_fullyear"


def fit(train):
    st = K.fit_coefs(None)
    st["provenance"]["rule"] = NAME
    return st


def predict(state, snaps, bands):
    s = snaps.reset_index(drop=True)
    b1 = K.corpus_mu(state, s)
    return C.serve(s, bands, np.where(np.isfinite(b1), (C.num(s, "v2_mean") + b1) / 2.0, np.nan))
