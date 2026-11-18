"""Dev-scorecard control: t3-r3 floor + remaining rise from hourly METAR (EF 10q). See remaining_rise."""
from weather.reporting.scorecards.free_source_candidates import f1_common

NAME = "control_t3r3_metar"


def fit(train):
    return f1_common.fit(train, None)


def predict(state, snaps, bands):
    return f1_common.predict(state, snaps, bands)
