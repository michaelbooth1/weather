"""Synthetic independent-review witnesses; no live clients or account calls.

Guards: B058 pre-POST aborts, delayed lifecycle events, peer cash, setup and owner terms.
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_f2_repost import fixture
from weather.market.lfc_ledger import Ledger, LedgerUnavailable
from weather.market.lfc_recording_io import strict_json
from weather.market.mm_stage2_hold import HoldEnd


@pytest.mark.parametrize('reason', ['ledger_clock_regressed', 'ledger_write_failed',
                                  'ledger_changed_underneath', 'require_account'])
def test_intent_refusal_before_any_durable_intent_is_not_ambiguous_placement(tmp_path, monkeypatch, reason):
    controller, account, status, ledger, clock, runtime, read = fixture(tmp_path)
    account.fills_enabled = False
    def refused(**kwargs):
        raise LedgerUnavailable(reason)
    monkeypatch.setattr(ledger, 'intent', refused)
    result = controller.run()
    assert ledger.legs == {} and not ledger.unacknowledged_intents()
    assert not result['unknown_submit'], result
    assert all(raw.memory.orders == {} for raw in account.raws)
    assert any(strict_json(line)['event'] == 'pre_post_abort'
               for line in controller.bands[0].journal.path.read_bytes().splitlines())


def test_durable_intent_followed_by_snapshot_failure_remains_ambiguous(tmp_path, monkeypatch):
    controller, account, status, ledger, clock, runtime, read = fixture(tmp_path)
    account.fills_enabled = False
    original = ledger.intent
    def refused(**kwargs):
        original(**kwargs)
        raise LedgerUnavailable('ledger_snapshot_write_failed')
    monkeypatch.setattr(ledger, 'intent', refused)
    result = controller.run()
    assert ledger.unacknowledged_intents() and result['unknown_submit']
    assert all(raw.memory.orders == {} for raw in account.raws)


def test_twelve_band_intents_with_equal_timestamps_have_monotonic_sequences(tmp_path):
    controller, account, status, ledger, clock, runtime, read = fixture(tmp_path, k=12)
    try:
        for band in controller.bands:
            ledger.intent(session_id=band.session_id, intent_key=band.session_id + ':same-clock',
                condition_id=band.condition, token_id=band.tokens[0], price=str(band.prices[0]),
                size='20', fee_rate_bps='0')
        rows = [row for row in ledger.rows if row['event'] == 'leg_intent']
        assert len(rows) == 12 and len({r['recorded_at_utc'] for r in rows}) == 1
        assert [r['sequence'] for r in rows] == sorted({r['sequence'] for r in rows})
        reopened = Ledger.open(ledger.path, clock=clock.now)
        assert len(reopened.legs) == 12 and reopened.previous == ledger.previous
    finally:
        for band in controller.bands:
            band.journal.close()
        controller.journal.close()


@pytest.mark.parametrize('mutation', ['partial_append', 'same_length_edit', 'missing'])
def test_intent_absence_never_waives_changed_or_unreadable_history(tmp_path, mutation):
    controller, account, status, ledger, clock, runtime, read = fixture(tmp_path)
    try:
        assert ledger.intent_proven_absent('not-appended')
        if mutation == 'partial_append':
            with ledger.path.open('ab') as handle:
                handle.write(b'{')
        elif mutation == 'same_length_edit':
            with ledger.path.open('r+b') as handle:
                handle.write(b'!')
        else:
            ledger.path.unlink()
        assert not ledger.intent_proven_absent('not-appended')
    finally:
        for band in controller.bands:
            band.journal.close()
        controller.journal.close()


@pytest.mark.parametrize('transition,status,matched,proved', [
    ('UPDATE', 'LIVE', '2', '2'), ('UPDATE', 'LIVE', '1', '2'),
    ('CANCELLATION', None, '0', '0'), ('CANCELLATION', None, '2', '2')])
def test_delayed_real_shaped_order_frame_cannot_end_a_proven_terminal_leg(transition, status, matched, proved):
    # No recorded user-channel JSON fixture was found. These documented wire
    # fields pass the real exact-scope normalizer; no fake normalized row hides
    # the optional status field or the UPDATE/CANCELLATION transition.
    from weather.market.mm_official_adapter import normalize_official_user_event
    from weather.market.lfc_f2_repost import filtered_events
    maker = '0x' + 'a' * 40
    raw = {'event_type': 'order', 'id': 'ours', 'market': 'condition', 'asset_id': 'yes',
           'maker_address': maker, 'type': transition, 'original_size': '20', 'size_matched': matched}
    if status is not None:
        raw['status'] = status
    rows = normalize_official_user_event(raw, maker_address=maker, condition_id='condition', token_id='yes')
    leg = {'session_id': 'band', 'status': 'terminal', 'size_matched': proved, 'size': '20'}
    band = SimpleNamespace(session_id='band', ledger=SimpleNamespace(by_order={'ours': 'key'}, legs={'key': leg}),
                           journal=SimpleNamespace(record=lambda *a, **k: None))
    assert filtered_events(band, rows) == []
    assert leg['size_matched'] == proved and leg['status'] == 'terminal'


@pytest.mark.parametrize('matched', ['2.01', None, '-1', 'NaN'])
def test_delayed_order_frame_never_hides_new_or_unreadable_fill_quantity(matched):
    from weather.market.lfc_f2_repost import filtered_events
    leg = {'session_id': 'band', 'status': 'terminal', 'size_matched': '2', 'size': '20'}
    band = SimpleNamespace(session_id='band', ledger=SimpleNamespace(by_order={'ours': 'key'}, legs={'key': leg}),
                           journal=SimpleNamespace(record=lambda *a, **k: None))
    with pytest.raises(HoldEnd):
        filtered_events(band, [{'order_id': 'ours', 'status': 'LIVE', 'size_matched': matched}])


@pytest.mark.parametrize('case', ['live_leg', 'foreign_id', 'conflicting_id'])
def test_delayed_replay_exemption_never_releases_live_or_foreign_reserves(case):
    from weather.market.lfc_f2_repost import filtered_events
    leg = {'session_id': 'band', 'status': 'posted' if case == 'live_leg' else 'terminal',
           'size_matched': '2', 'size': '20'}
    band = SimpleNamespace(session_id='band', ledger=SimpleNamespace(by_order={'ours': 'key'}, legs={'key': leg}),
                           journal=SimpleNamespace(record=lambda *a, **k: None))
    event = {'order_id': 'foreign' if case == 'foreign_id' else 'ours', 'size_matched': '2'}
    if case == 'conflicting_id':
        event['id'] = 'foreign'
    assert filtered_events(band, [event]) == [event]
    assert leg['status'] == ('posted' if case == 'live_leg' else 'terminal')


@pytest.mark.parametrize('phase', ['authorize', 'raw_before_post'])
def test_peer_partial_fill_defers_a_post_then_resumes_after_reconciliation(tmp_path, monkeypatch, phase):
    controller, account, status, ledger, clock, runtime, read = fixture(tmp_path, seconds=300)
    account.fills_enabled = False
    first, second = controller.bands
    triggered = []
    def fill():
        if not triggered:
            order = next(r for r in account.raws[0].memory.orders.values() if r['status'] == 'LIVE')
            order.update(size_matched='1', associate_trades=['fill-' + order['id']])
            triggered.append(clock.seconds)
    if phase == 'authorize':
        ordinary = second.authorize_post
        def authorize(*args, **kwargs):
            fill()
            return ordinary(*args, **kwargs)
        monkeypatch.setattr(second, 'authorize_post', authorize)
    else:
        ordinary = account.raws[1].before_post
        def before_post(*args, **kwargs):
            fill()
            return ordinary(*args, **kwargs)
        monkeypatch.setattr(account.raws[1], 'before_post', before_post)
    result = controller.run()
    assert triggered and second.posts >= 2, (result, controller.results)
    assert controller.results[second.session_id]['reason'] == 'fixed_end'
    assert account.cancel_all_calls == [300]
    assert result['cleanup_ok'] and not result['unknown_submit'], result
    assert any(leg['size_matched'] == '1' for leg in ledger.legs.values())
    assert all(band.submits <= 10 for band in controller.bands)


def test_peer_cash_deferral_cannot_waive_an_already_durable_intent(tmp_path, monkeypatch):
    from weather.market.lfc_f2_controller import PeerCashPending
    controller, account, status, ledger, clock, runtime, read = fixture(tmp_path)
    account.fills_enabled = False
    original = ledger.intent
    attempts = []
    def recorded(**kwargs):
        attempts.append(kwargs['intent_key'])
        original(**kwargs)
        raise PeerCashPending()
    monkeypatch.setattr(ledger, 'intent', recorded)
    result = controller.run()
    assert len(attempts) == 1 and result['unknown_submit'], (attempts, result)
    assert ledger.unacknowledged_intents()
    assert all(raw.memory.orders == {} for raw in account.raws)
