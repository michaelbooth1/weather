"""Guards: B061 bounded cash deferral without budget consumption or rapid polls."""
from datetime import datetime

import pytest

from tests.market.test_lfc_f2_repost import fixture
from weather.market.lfc_recording_io import strict_json


@pytest.mark.parametrize('phase', ['authorize', 'raw_before_post'])
def test_owner_withdrawal_retires_waiting_band_within_120_seconds(tmp_path, monkeypatch, phase):
    controller, account, status, ledger, clock, runtime, read = fixture(tmp_path, seconds=600)
    account.fills_enabled = False
    band = controller.bands[1]
    raw = account.raws[1]
    ordinary, authorize = raw.balances, band.authorize_post
    began = []
    def enter(*args, **kwargs):
        if phase == 'authorize' and not began: began.append(clock.seconds)
        return authorize(*args, **kwargs)
    submit = raw.submit
    def raw_enter(*args, **kwargs):
        if not began: began.append(clock.seconds)
        return submit(*args, **kwargs)
    def withdrawal():
        row = ordinary()
        if began:
            row['available_collateral'] = '299'
            row['collateral_evidence']['balance'] = '299000000'
        return row
    monkeypatch.setattr(band, 'authorize_post', enter)
    if phase == 'raw_before_post': monkeypatch.setattr(raw, 'submit', raw_enter)
    monkeypatch.setattr(raw, 'balances', withdrawal)
    result = controller.run()
    assert began and band.posts == 0 and band.submits == 0
    end = datetime.fromisoformat(ledger.sessions[band.session_id]['end']['recorded_at_utc'])
    assert (end - clock.base).total_seconds() - began[0] <= 120
    assert controller.results[band.session_id]['reason'] == 'peer_cash_wait_expired'
    rows = [strict_json(line) for line in band.journal.path.read_bytes().splitlines()]
    polls = [datetime.fromisoformat(row['recorded_at_utc']).timestamp()
             for row in rows if row['event'] == 'f2_wait_balances_request']
    assert polls and len(polls) <= 24
    assert all(b - a >= 5 for a, b in zip(polls, polls[1:]))
    assert not result['unknown_submit'] and account.cancel_all_calls == [600]
