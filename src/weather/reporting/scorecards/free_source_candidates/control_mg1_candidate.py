"""Dev-scorecard control: MG-1 (r-t5-inc-c1) from captured NBM v2. See mg1."""
from weather.reporting.scorecards.free_source_candidates import mg1

NAME = "control_mg1"
MEMBER = None


def fit(train):
    """Zero fitted parameters: ``train`` is never read."""
    return {"provenance": mg1.provenance(MEMBER)}


def predict(state, snaps, bands):
    return mg1.predict(snaps, bands, MEMBER)
