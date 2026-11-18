"""Dev-scorecard candidate F1u (sensitivity, information upper bound): t3-r3 with the running high
refreshed from every 1-minute archive row, whole degree F, available 2 minutes after valid.
See remaining_rise."""
from weather.reporting.scorecards.free_source_candidates import f1_common, remaining_rise

NAME = "f1u_onemin_m1f_lat2"


def fit(train):
    return f1_common.fit(train, remaining_rise.M1F)


def predict(state, snaps, bands):
    return f1_common.predict(state, snaps, bands)
