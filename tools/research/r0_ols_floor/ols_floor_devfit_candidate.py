"""Dev-scorecard candidate: L3 arm A dev-fitted walk-forward (see weather.calibration.r0_ols_floor_devfit)."""
from weather.calibration import r0_ols_floor_devfit as devfit

NAME = "l3_ols_floor_devfit"


def fit(train):
    return devfit.fit_ols(train, with_nbm=False)


def predict(state, snaps, bands):
    return devfit.predict_ols(state, snaps, bands)
