"""T044 RECHECK1: synthetic attacks on the fourteen fixes. No external IO.

Guards: B061 delayed-go wrapper budget and malformed-policy refusal.

Desired-behavior assertions are retained even when they expose a product defect.
"""
from datetime import datetime, timedelta, timezone
import json

import pytest

from tests.market.test_lfc_campaign import MAKER, Mutexes
from tests.market.test_lfc_f2_repost import fixture
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_f2_breadth import example_policy
from weather.market.lfc_recording_io import strict_json


def wrapper_deadline(tmp_path, row, start):
    from tests.operations.test_lfc_campaign_task import powershell
    path = tmp_path / 'synthetic-policy.json'
    path.write_text(json.dumps(row))
    result = powershell("(Get-LfcCampaignDeadline -CampaignPath '" + str(path).replace("'", "''") +
        "' -NowUtc ([DateTimeOffset]'" + start.isoformat() + "')).ToString('o')")
    assert result.returncode == 0, result.stderr
    return datetime.fromisoformat(result.stdout.strip())


@pytest.mark.spawns
@pytest.mark.parametrize('delay_seconds,window_end', [(192, '09:15:00'), (2700, '11:00:00')])
def test_wrapper_preserves_child_end_and_cleanup_margin_after_delayed_go(tmp_path, delay_seconds, window_end):
    # Both schedules pass the real v0.3 parser. Delay can be setup or the
    # coordinator's permitted transient admission retries before its date claim.
    row = example_policy()
    row.update(enabled=True, start_window_toronto=['09:00:00', window_end], max_session_seconds=3600)
    policy = parse_policy(row)
    entry = next(e for e in policy.entries if e.local_date == '2026-11-11')
    wrapper_start = entry.start
    actual_start = wrapper_start + timedelta(seconds=delay_seconds)
    assert entry.permits(actual_start)
    child_end = entry.session_end(actual_start)
    deadline = wrapper_deadline(tmp_path, row, wrapper_start)
    assert deadline >= child_end + timedelta(minutes=30), {
        'wrapper_start': str(wrapper_start), 'actual_start': str(actual_start),
        'child_end': str(child_end), 'wrapper_kill': str(deadline),
        'cleanup_seconds': (deadline - child_end).total_seconds()}


@pytest.mark.spawns
def test_unparseable_deadline_policy_keeps_short_refused_window(tmp_path):
    now = datetime(2026, 11, 11, 14, tzinfo=timezone.utc)
    assert wrapper_deadline(tmp_path, {'schema_version': 'lfc_campaign_policy_v0.3'}, now) == now + timedelta(minutes=30)
