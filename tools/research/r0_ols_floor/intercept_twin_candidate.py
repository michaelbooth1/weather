"""Dev-scorecard twin: MG-1 plus a per-hour (07-12) intercept only, no observation information."""
from weather.calibration import r0_ols_floor_devfit as devfit

NAME = "l3_intercept_twin"


def fit(train):
    return devfit.fit_intercept(train)


def predict(state, snaps, bands):
    return devfit.predict_intercept(state, snaps, bands)
