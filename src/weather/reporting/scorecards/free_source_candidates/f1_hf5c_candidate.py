"""Dev-scorecard candidate F1 (primary): t3-r3 with the running high refreshed from the IEM 1-minute
archive degraded to a 5-minute, whole-degree-C product available 10 minutes after valid (a training
proxy for live MADIS HF-METAR). See remaining_rise."""
from weather.reporting.scorecards.free_source_candidates import f1_common, remaining_rise

NAME = "f1_onemin_hf5c_lat10"


def fit(train):
    return f1_common.fit(train, remaining_rise.HF5C)


def predict(state, snaps, bands):
    return f1_common.predict(state, snaps, bands)
