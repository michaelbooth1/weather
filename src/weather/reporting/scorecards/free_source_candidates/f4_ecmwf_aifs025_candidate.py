"""Dev-scorecard candidate F4: MG-1 recentred halfway to captured Open-Meteo ecmwf_aifs025. See mg1."""
from weather.reporting.scorecards.free_source_candidates import mg1

NAME = "f4_ecmwf_aifs025"
MEMBER = 'ecmwf_aifs025'


def fit(train):
    """Zero fitted parameters: ``train`` is never read."""
    return {"provenance": mg1.provenance(MEMBER)}


def predict(state, snaps, bands):
    return mg1.predict(snaps, bands, MEMBER)
