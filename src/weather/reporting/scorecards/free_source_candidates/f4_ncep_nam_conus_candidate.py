"""Dev-scorecard candidate F4: MG-1 recentred halfway to captured Open-Meteo ncep_nam_conus. See mg1."""
from weather.reporting.scorecards.free_source_candidates import mg1

NAME = "f4_ncep_nam_conus"
MEMBER = 'ncep_nam_conus'


def fit(train):
    """Zero fitted parameters: ``train`` is never read."""
    return {"provenance": mg1.provenance(MEMBER)}


def predict(state, snaps, bands):
    return mg1.predict(snaps, bands, MEMBER)
