"""Guards: T113 copied evidence, causal book clocks, touch/fill separation.

All files are deterministic temporary fixtures, never the ignored live store.
"""
from datetime import timedelta
from decimal import Decimal as D
import json
from types import SimpleNamespace

import pytest

from weather.market.lfc_pair_completion import OwnLot, instant, inventory
from weather.market.lfc_pair_replay import (
    CopiedInputs, RecordedBook, candidate, full_size_touch_sensitivity, read_books, replay_fills,
    residual_variance, touch_evidence,
)
from weather.market.lfc_recording_io import file_sha
from weather.market.lfc_pair_replay_fills import session_directories


def test_real_a091_short_session_id_resolves_to_the_full_manifest_directory():
    folder = 'session-F2-078690f3f7d243799e3acd6c677c7f09'
    receipts = {folder+'/f2_manifest.json': {}, folder+'/band-7/journal.jsonl': {}}
    assert session_directories(receipts, ['078690f3']) == {'078690f3': folder}
    with pytest.raises(ValueError, match='replay_session_binding'):
        session_directories(receipts | {'session-F2-078690f3other/f2_manifest.json': {}}, ['078690f3'])
    with pytest.raises(ValueError, match='replay_session_binding'):
        session_directories(receipts, ['missing'])


AT = instant('2026-11-13T20:00:00Z')


def book(at=AT, *, no_ask='.77', no_ask_size='100'):
    level = lambda p, s: {'price': p, 'size': s}
    snapshot = {'condition_id': 'c', 'token_ids': ['yes', 'no'], 'observed_at_utc': at.isoformat(),
        'quote_inputs': {'yes_bids': [level('.24', '100')], 'yes_asks': [level('.28', '100')],
            'no_bids': [level('.72', '100')], 'no_asks': [level(no_ask, no_ask_size)],
            'reward_min_size': '20', 'reward_max_spread_cents': '4.5', 'reward_rate_per_day': '20'},
        'rules': {t: {'tick_size': '.01', 'min_order_size': '5', 'fee_rate_bps': '1000'} for t in ('yes', 'no')}}
    return RecordedBook(at, snapshot, 'copied/journal.jsonl:1')


def policy(**changes):
    raw = {'campaign_id': 'campaign', 'min_reward_rate': '0', 'min_book_depth': '20',
           'share_many_range': ['0', '1'], 'leg_price_range': ['.17', '.80'],
           'fill_cooldown_seconds': 60, 'per_band_daily_filled_cap_pusd': '30'}
    return SimpleNamespace(raw=raw | changes)


def own(tid, oid, leg, size, price, at=AT):
    return OwnLot(tid, oid, 'campaign', 'c', leg, size, price, at)


def fill(number, *, leg='yes', size='20', price='.24'):
    return {'session': 'session', 'band': 'band-1', 'trade_id': f't{number}', 'order_id': f'o{number}',
            'leg': leg, 'size': size, 'price': price, 'time': (AT+timedelta(seconds=number)).isoformat(),
            'status': 'CONFIRMED', 'side': 'BUY', 'trader_side': 'MAKER', 'market': 'austin'}


def test_touch_uses_actual_complementary_ask_and_never_infers_it_from_yes():
    later = [book(AT+timedelta(seconds=60), no_ask='.75'),
             book(AT+timedelta(seconds=120), no_ask='.74', no_ask_size='3')]
    result = touch_evidence(later, leg=1, price=D('.74'), after=AT, end=AT+timedelta(minutes=3))
    assert result['touch_evidence'] is True
    assert result['first_touch_at_utc'] == later[1].at.isoformat()
    assert result['first_touch_displayed_size'] == '3'
    assert result['touch_book_count'] == 1 and result['later_book_count'] == 2
    assert 'fill' not in result and 'filled_shares' not in result


def test_no_later_book_is_missing_touch_evidence_not_a_negative():
    result = touch_evidence([book()], leg=1, price=D('.74'), after=AT, end=AT+timedelta(minutes=1))
    assert result['touch_evidence'] is None and result['later_book_count'] == 0


def test_touch_excludes_current_book_post_end_books_and_zero_size_levels():
    later = [book(no_ask='.74'), book(AT+timedelta(seconds=1), no_ask='.74', no_ask_size='0'),
             book(AT+timedelta(seconds=61), no_ask='.74')]
    result = touch_evidence(later, leg=1, price=D('.74'), after=AT, end=AT+timedelta(seconds=60))
    assert result['touch_evidence'] is None


def test_book_clock_uses_collection_time_and_skips_nonbook_rows(tmp_path):
    path = tmp_path / 'journal.jsonl'
    b = book()
    rows = [json.dumps({'event': 'irrelevant', 'not_a_book': True}),
            json.dumps({'event': 'market_snapshot', 'recorded_at_utc': (AT+timedelta(seconds=2)).isoformat(),
                        'snapshot': b.snapshot})]
    path.write_text('\n'.join(rows)+'\n', encoding='utf-8')
    result = read_books(path, condition_id='c', source='copied/journal.jsonl')
    assert len(result) == 1 and result[0].at == AT and result[0].source.endswith(':2')


@pytest.mark.parametrize('condition,recorded', [('foreign', AT), ('c', AT-timedelta(seconds=1))])
def test_book_scope_or_future_collection_refuses(tmp_path, condition, recorded):
    path = tmp_path / 'journal.jsonl'
    snapshot = book().snapshot | {'condition_id': condition}
    path.write_text(json.dumps({'event': 'market_snapshot', 'snapshot': snapshot,
                               'recorded_at_utc': recorded.isoformat()})+'\n', encoding='utf-8')
    with pytest.raises(ValueError, match='replay_book_'):
        read_books(path, condition_id='c', source='copy')


def test_captured_proposal_reuses_normal_price_before_applying_cap():
    state = inventory([own('t', 'o', 0, 20, '.24')], campaign_id='campaign', condition_id='c')
    result = candidate(state, book(), policy=policy(), offset='.015')
    assert result['uncapped_completion_price'] == '0.72'
    assert result['capped_completion_price'] == '0.72' and result['completion_pair_cap'] == '0.745'
    assert result['screen_refusal'] is None


def test_captured_thin_book_never_passes_because_margin_is_good():
    state = inventory([own('t', 'o', 0, 20, '.24')], campaign_id='campaign', condition_id='c')
    thin = book()
    thin.snapshot['quote_inputs']['yes_bids'][0]['size'] = '20'
    result = candidate(state, thin, policy=policy(min_book_depth='21'), offset='.015')
    assert result['screen_refusal'] == 'thin_book_depth'


def test_miami_second_same_side_fill_is_suppressed_without_assuming_touch_fills():
    fills = [fill(1, price='.26'), fill(2, price='.28', size='14.263889')]
    rows, a, b = replay_fills(fills, {'c': [book(AT+timedelta(seconds=70))]},
        {('session', 'band-1'): {'condition_id': 'c', 'offset': '.015'}},
        policy=policy(), end=AT+timedelta(hours=1))
    assert rows[0]['b_observed_fill_admitted'] is True
    assert rows[1]['b_observed_fill_refusal'] == 'overheld_side_suppressed'
    assert a['c'].u == D('34.263889') and b['c'].u == 20
    assert not b['c'].pairs and not b['c'].flips


def test_austin_observed_76_cent_no_is_incompatible_with_b():
    fills = [fill(1), fill(2, leg='no', size='5', price='.76'), fill(3, leg='no', size='5', price='.76')]
    rows, a, b = replay_fills(fills, {'c': [book(AT+timedelta(seconds=70))]},
        {('session', 'band-1'): {'condition_id': 'c', 'offset': '.015'}},
        policy=policy(), end=AT+timedelta(hours=1))
    assert a['c'].u == 10 and b['c'].u == 20
    assert [r['b_observed_fill_refusal'] for r in rows[1:]] == ['observed_price_exceeds_pair_cap']*2


def test_admissible_completion_can_over_complete_and_variance_uses_signed_u_squared():
    fills = [fill(1, size='5', price='.3'), fill(2, leg='no', size='20', price='.6')]
    _, _, states = replay_fills(fills, {'c': []},
        {('session', 'band-1'): {'condition_id': 'c', 'offset': '.015'}},
        policy=policy(), end=AT+timedelta(hours=1))
    assert states['c'].u == -15 and len(states['c'].flips) == 1
    assert residual_variance(states, {'c': '.4'}) == 54


def test_cap_refuses_completion_in_filtered_trace():
    _, _, states = replay_fills([fill(1)], {'c': []},
        {('session', 'band-1'): {'condition_id': 'c', 'offset': '.015'}},
        policy=policy(), end=AT+timedelta(hours=1))
    assert states['c'].u == 20
    rows, _, _ = replay_fills([fill(1)], {'c': [book(AT+timedelta(seconds=70))]},
        {('session', 'band-1'): {'condition_id': 'c', 'offset': '.015'}},
        policy=policy(per_band_daily_filled_cap_pusd='19'), end=AT+timedelta(hours=1))
    assert rows[0]['screen_refusal'] == 'per_band_daily_filled_cap'
    assert rows[0]['touch_evidence'] is None


def copied(tmp_path):
    root = tmp_path / 'data'
    root.mkdir()
    path = root / 'books.jsonl'
    path.write_text('{}\n', encoding='utf-8')
    (root / 'copy_manifest.json').write_text(json.dumps([{'copy': str(path), 'length': path.stat().st_size,
                                                        'sha256': file_sha(path)}]), encoding='utf-8')
    return root, path


def test_only_hash_bound_input_copies_can_be_read(tmp_path):
    root, path = copied(tmp_path)
    inputs = CopiedInputs(root)
    assert inputs.path('books.jsonl') == path
    path.write_text('{"changed": true}\n', encoding='utf-8')
    with pytest.raises(ValueError, match='replay_copy_changed'):
        inputs.path('books.jsonl')


def test_unlisted_input_and_manifest_escape_refuse(tmp_path):
    root, path = copied(tmp_path)
    (root / 'other.json').write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='replay_unlisted_input'):
        CopiedInputs(root).path('other.json')
    escaped = tmp_path / 'outside.json'
    escaped.write_text('{}', encoding='utf-8')
    manifest = root / 'copy_manifest.json'
    manifest.write_text(json.dumps([{'copy': str(escaped)}]), encoding='utf-8')
    with pytest.raises(ValueError):
        CopiedInputs(root)


def test_twenty_share_touch_sensitivity_reports_flip_without_calling_it_a_fill():
    state = inventory([own('t', 'o', 0, '5.31', '.27')], campaign_id='campaign', condition_id='c')
    rows = [{'condition_id': 'c', 'market': 'los-angeles', 'completion_leg': 1,
             'touch_evidence': True, 'capped_completion_price': '.69',
             'first_touch_at_utc': (AT+timedelta(minutes=1)).isoformat(),
             'first_touch_displayed_size': '5'}]
    result = full_size_touch_sensitivity(rows, {'c': state}, {'c': '.33'})
    assert state.u == D('5.31')  # sensitivity never mutates the filtered trace.
    assert result['hypothetical_over_completions'] == 1
    scenario = result['scenarios'][0]
    assert scenario['hypothetical_u_after'] == '-14.69'
    assert scenario['observed_fill'] is False and scenario['assumed_execution'] is True
    assert scenario['displayed_size_at_touch'] == '5'
