"""Observed campaign/window and selected-band clocks, never trading authority.

Intervals require two matching observations at most ninety seconds apart.
Missing observations and state transitions remain unknown, including task-off gaps.
"""
import uuid

from weather.market.mm_stage2_hold import digest, utc


MAX_GAP_SECONDS = 90


def interval(previous, current):
    start, end = utc(previous['at_utc']), utc(current['at_utc'])
    if end < start:
        raise ValueError('eligible_clock_reversed')
    same = all(previous.get(k) == current.get(k) for k in ('eligible', 'reason', 'policy_sha256', 'scope'))
    known = same and (end - start).total_seconds() <= MAX_GAP_SECONDS
    return {'start_utc': start.isoformat(), 'end_utc': end.isoformat(),
            'seconds': (end - start).total_seconds(),
            'eligible': current['eligible'] if known else None,
            'reason': current['reason'] if known else 'observation_gap_or_transition',
            'previous_observation_sha256': digest(previous)}


def totals(rows, *, start, end):
    """Sum elapsed time; uncovered edges/gaps never become a denominator of zero."""
    start, end = utc(start), utc(end)
    cursor, eligible, ineligible = start, 0., 0.
    for row in sorted(rows, key=lambda r: r['start_utc']):
        left, right = max(start, utc(row['start_utc'])), min(end, utc(row['end_utc']))
        if right <= left:
            continue
        if left < cursor:
            raise ValueError('eligible_interval_overlap')
        seconds = (right - left).total_seconds()
        if row['eligible'] is True:
            eligible += seconds
        elif row['eligible'] is False:
            ineligible += seconds
        cursor = right
    unknown = (end - start).total_seconds() - eligible - ineligible
    return {'eligible_seconds': eligible, 'ineligible_seconds': ineligible,
            'unknown_seconds': unknown, 'denominator_complete': unknown == 0}


def campaign_observation(coordinator, policy, *, incidents=False):
    """Window/no-halt clock independent of enabled state; no new account reads."""
    if policy is None or not policy.f2:
        return
    now = utc(coordinator.clock.now())
    entry = next((e for e in policy.entries if e.start <= now < (e.fixed_end or e.session_end(e.start))), None)
    eligible = entry is not None and not coordinator.state.ledger.halted and not incidents
    reason = 'window_open_no_halt' if eligible else 'halt' if incidents or coordinator.state.ledger.halted else 'window_closed'
    point = {'at_utc': now.isoformat(), 'scope': 'campaign_window', 'eligible': eligible,
             'reason': reason, 'policy_sha256': policy.sha256,
             'enabled': policy.raw['enabled'], 'market_eligibility': 'unknown_without_fresh_band_screen'}
    day = now.date().isoformat()
    directory = coordinator.state.root / 'eligible-time' / day
    paths = sorted(directory.glob('*.json'))
    prior = coordinator.state.read(paths[-1]) if paths else None
    if prior and digest({k: prior[k] for k in ('kind', 'observation', 'interval')}) != prior['content_sha256']:
        raise ValueError('eligible_observation_hash')
    previous = prior['observation'] if prior else None
    body = {'kind': 'eligible_time_observation', 'observation': point,
            'interval': interval(previous, point) if previous else None}
    coordinator.state.save('eligible-time/' + day + '/' + now.strftime('%H%M%S%f') + '-' + uuid.uuid4().hex + '.json',
                           {**body, 'content_sha256': digest(body)})


def band_observation(band, eligible, reason):
    """Record passed/failed ordinary screens separately from order/reward clocks."""
    point = {'at_utc': band.clock.now().isoformat(), 'scope': band.session_id,
             'policy_sha256': band.campaign_policy.sha256, 'eligible': eligible, 'reason': reason}
    previous = getattr(band, '_eligibility_observation', None)
    band.journal.record('band_eligible_time', observation=point,
        interval=interval(previous, point) if previous else None,
        acknowledged_order_ids=sorted(band.active),
        reward_qualification='unknown_without_current_scoring_and_remaining_size_proof')
    band._eligibility_observation = point


def running_observation(coordinator, *, halted=False):
    now = coordinator.clock.now()
    previous = getattr(coordinator, '_window_observation', None)
    if previous and not halted and (now - utc(previous['at_utc'])).total_seconds() < 30:
        return
    point = {'at_utc': now.isoformat(), 'scope': 'campaign_window',
             'policy_sha256': coordinator.policy.sha256,
             'eligible': not halted and not coordinator.ledger.halted and
                 coordinator.entry.start <= now < coordinator.entry.session_end(coordinator.entry.start),
             'reason': 'quoting_halted' if halted else 'window_open_no_halt'}
    coordinator.retain('campaign_eligible_time', observation=point,
        interval=interval(previous, point) if previous else None)
    coordinator._window_observation = point
