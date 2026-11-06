"""Fixture-only minute scoring regressions; no authenticated transport.

Guards: F2 R2 batched 60-second scoring, 1800-second accrual and nonfatal missed reads.
"""
import json
import pytest

from tests.market.test_re1_attended import setup
from weather.market.re1_attended import HoldEnd


def test_scoring_every_minute_accrual_independent_and_miss_nonfatal(tmp_path):
    session, venue, clock = setup(tmp_path)
    samples, accruals = [], []
    def scoring(ids):
        samples.append((clock.seconds, list(ids)))
        # The first two reads are the pinned immediate post-time samples.
        if len(samples) == 4:
            raise TimeoutError('synthetic')
        return {oid: True for oid in ids}
    venue.scoring = scoring
    venue.accrual = lambda day: accruals.append(clock.seconds) or {'day': day}
    result = session.run(rehearsal_seconds=181)
    rows = [json.loads(line) for line in session.journal.path.read_bytes().splitlines()]
    scored = [row for row in rows if row['event'] == 'scoring']
    missed = [row for row in rows if row['event'] == 'scoring_missed']
    assert result['reason'] == 'fixed_end' and result['cleanup_ok'] and not result['evidence_complete']
    assert len(samples) == 6 and all(len(ids) == 2 for _, ids in samples[2:])
    assert len(missed) == 1 and len(scored) == 6
    assert all(row['band'] == session.condition and type(row['scoring']) is bool and row['observed_at_utc']
               for row in scored)
    assert all(b[0] - a[0] == 60 for a, b in zip(samples[2:], samples[3:]))
    assert len(accruals) == 2  # initial minute plus final read, no minute accruals


def test_incomplete_scoring_is_missed_and_can_recover(tmp_path):
    session, venue, clock = setup(tmp_path)
    venue.scoring = lambda ids: {}
    result = session.run(rehearsal_seconds=61)
    rows = [json.loads(line) for line in session.journal.path.read_bytes().splitlines()]
    assert len([row for row in rows if row['event'] == 'scoring_missed']) == 2
    assert result['reason'] == 'fixed_end' and not result['scoring_seen']


def test_hold_end_is_never_swallowed_as_a_missed_sample(tmp_path):
    session, venue, clock = setup(tmp_path)
    def stop(*args):
        raise HoldEnd('heartbeat_stale')
    with pytest.raises(HoldEnd, match='heartbeat_stale'):
        session.sample('probe', stop)
    session.active = {'own': (0, session.prices[0])}
    venue.scoring = stop
    with pytest.raises(HoldEnd, match='heartbeat_stale'):
        session.sample_scoring()
    session.journal.close()
    rows = [json.loads(line) for line in session.journal.path.read_bytes().splitlines()]
    assert not any(row['event'] in {'missing_sample', 'scoring_missed'} for row in rows)
