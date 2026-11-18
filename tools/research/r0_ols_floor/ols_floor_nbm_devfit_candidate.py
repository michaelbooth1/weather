"""Dev-scorecard candidate: L3 arm A prime (A + NBM mean regressor) dev-fitted walk-forward (sensitivity)."""
from weather.calibration import r0_ols_floor_devfit as devfit

NAME = "l3_ols_floor_nbm_devfit"


def fit(train):
    return devfit.fit_ols(train, with_nbm=True)


def predict(state, snaps, bands):
    return devfit.predict_ols(state, snaps, bands)
