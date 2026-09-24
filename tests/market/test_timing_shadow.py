from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest

from weather.market.observation_clock import RemainingRiseEstimator
from weather.market.timing_shadow import ShadowBand, band_risk, routine_clock, timing_row
from tools.timing_shadow_20260924 import clock_baseline, future_moves, vector_risk, policy_masks

UTC = timezone.utc
DAY = date(2026, 9, 22)


def estimator():
    return RemainingRiseEstimator(date(2026, 8, 13), {q: (0, 0, 1, 2) for q in range(0, 1440, 15)}, 4)


def test_routine_clock_rollover_and_unknown_station():
    now = datetime(2026, 9, 22, 23, 59, tzinfo=UTC)
    assert routine_clock('CYYZ', now) == {'minutes_since_metar': 59, 'minutes_to_metar': 1}
    assert routine_clock('KLGA', now) == {'minutes_since_metar': 8, 'minutes_to_metar': 52}
    assert routine_clock('unknown', now)['minutes_to_metar'] is None
    with pytest.raises(ValueError):
        routine_clock('KLGA', now.replace(tzinfo=None))


@pytest.mark.parametrize('label,running,p,locked', [
    ('-3 to -2 C', -3, .75, False), ('-3 to -2 C', -1, 1., True),
    ('0 to 1 C', -1, .5, False), ('0 to 1 C', 0, .75, False),
    ('0 C or above', 0, 1., True), ('0 C or below', 1, 1., True),
])
def test_per_band_risk_and_vector_parity(label, running, p, locked):
    band = ShadowBand.from_label('fixture', DAY, label, 'C')
    result = band_risk(band, estimator(), minute=601, running_degree=running, local_date=DAY)
    assert result['p_band_decided'] == p
    assert result['observed_locked'] == locked
    vector, _ = vector_risk(band, estimator(), np.array([running, np.nan]), np.array([601, 601]))
    assert vector[0] == p and np.isnan(vector[1])


def test_future_target_and_missing_observations_abstain():
    band = ShadowBand.from_label('future', DAY+timedelta(days=1), '20 C', 'C')
    now = datetime(2026, 9, 22, 13, tzinfo=UTC)
    row = timing_row('CYYZ', now, band, estimator(), station_timezone='UTC', running_degree=20,
                     observation_cutoff=now-timedelta(minutes=5), publications={})
    assert row['p_band_decided'] is None and row['day_ahead'] == 1
    assert row['model_clocks']['nbm_cycle']['minutes_since'] == 0
    assert row['counts_toward_trading_readiness'] is False
    with pytest.raises(ValueError):
        timing_row('CYYZ', now, band, estimator(), station_timezone='UTC', running_degree=20,
                   observation_cutoff=now+timedelta(minutes=1))


def test_forecast_cannot_reach_training_dates_or_wrong_units():
    band = ShadowBand.from_label('x', date(2026, 8, 12), '20 C', 'C')
    with pytest.raises(ValueError):
        band_risk(band, estimator(), minute=60, running_degree=20, local_date=band.target_date)
    with pytest.raises(ValueError):
        ShadowBand.from_label('x', DAY, '80 F', 'C')


def test_sparse_estimator_preserves_only_observed_lock():
    sparse = RemainingRiseEstimator(date(2026, 8, 13), {}, 20)
    band = ShadowBand.from_label('x', DAY, '20 C', 'C')
    assert band_risk(band, sparse, minute=60, running_degree=20, local_date=DAY)['p_band_decided'] is None
    assert band_risk(band, sparse, minute=60, running_degree=21, local_date=DAY)['p_band_decided'] == 1


def test_price_moves_use_future_seconds_and_exact_three_cent_threshold():
    eligible, large = future_moves([0, 1, 300, 301, 700], [.5, .51, .53, .49, .8])
    assert eligible.tolist() == [True, True, True, False, False]
    assert large.tolist() == [True, False, True, False, False]
    with pytest.raises(ValueError):
        future_moves([1, 1], [.3, .7])


def test_move_algorithm_matches_bruteforce():
    rng = np.random.default_rng(95)
    times = np.cumsum(rng.integers(1, 90, 200))
    prices = rng.random(200)
    eligible, large = future_moves(times, prices)
    for i, t in enumerate(times):
        future = prices[(times > t) & (times <= t+300)]
        assert eligible[i] == bool(len(future))
        assert large[i] == (bool(len(future)) and np.max(np.abs(future-prices[i])) >= .03)


@pytest.mark.parametrize('phase', [0, 15, 30, 45])
def test_fixed_clock_baseline_exactly_matches_each_partial_hour(phase):
    minutes = np.arange(47, 184)
    mask = minutes % 7 < 3
    baseline = clock_baseline(minutes, mask, phase)
    for hour in np.unique(minutes//60):
        subset = minutes//60 == hour
        assert baseline[subset].sum() == mask[subset].sum()


def test_policy_windows_are_half_open_and_unknown_t3_does_not_trigger():
    minutes = np.arange(60)
    risks = {lag: np.full(60, np.nan) for lag in (0, 5, 15)}
    masks = policy_masks(minutes, 53, {'gfs': [], 'hrrr': []}, risks)
    assert np.flatnonzero(masks['metar_2']).tolist() == [51, 52, 53, 54]
    assert not masks['t3_95'].any()
    assert not masks['gfs_5'].any()
