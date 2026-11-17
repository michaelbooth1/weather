"""Guards: T122 observed eligible denominators; no inferred task-off coverage."""
from datetime import timedelta
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_f2_controller import setup
from weather.market.lfc_eligible_time import campaign_observation, interval, totals
from weather.market.mm_stage2_hold import utc


def point(at, eligible=True, reason='screen_passed'):
    return {'at_utc': at, 'eligible': eligible, 'reason': reason, 'scope': 'band', 'policy_sha256': 'a'}


def test_elapsed_denominator_and_unknown_transition_and_missing_edges():
    first = utc('2026-11-11T14:00:00Z')
    points = [point((first + timedelta(seconds=n)).isoformat()) for n in (10, 40, 70, 200)]
    rows = [interval(a, b) for a, b in zip(points, points[1:])]
    got = totals(rows, start=first, end=first + timedelta(seconds=220))
    assert got == {'eligible_seconds': 60, 'ineligible_seconds': 0,
                   'unknown_seconds': 160, 'denominator_complete': False}
    assert interval(points[0], dict(points[1], eligible=False))['eligible'] is None
    with pytest.raises(ValueError, match='overlap'):
        totals(rows + rows[:1], start=first, end=first + timedelta(seconds=220))


def test_disabled_observation_is_still_eligible_and_halt_is_separate(tmp_path):
    controller, account, status, ledger, clock = setup(tmp_path)
    policy = controller.policy
    saved = []
    state = SimpleNamespace(root=tmp_path, ledger=ledger, save=lambda path, row: saved.append(row))
    coordinator = SimpleNamespace(state=state, clock=clock)
    policy.raw['enabled'] = False
    campaign_observation(coordinator, policy)
    assert saved[-1]['observation']['eligible'] is True
    assert saved[-1]['observation']['enabled'] is False
    campaign_observation(coordinator, policy, incidents=True)
    assert saved[-1]['observation']['eligible'] is False
    assert saved[-1]['observation']['reason'] == 'halt'


def test_controller_retains_band_intervals_without_changing_orders(tmp_path):
    controller, account, status, ledger, clock = setup(tmp_path)
    result = controller.run()
    from weather.market.lfc_recording_io import strict_json
    rows = [strict_json(raw) for raw in controller.bands[0].journal.path.read_bytes().splitlines()]
    observations = [r for r in rows if r['event'] == 'band_eligible_time']
    assert observations[0]['observation']['eligible'] is True
    assert observations[-1]['observation']['reason'] == 'quoting_halted'
    assert any(r['interval'] and r['interval']['eligible'] is True for r in observations)
    assert result['cleanup_ok'] and result['post_count'] == 4
