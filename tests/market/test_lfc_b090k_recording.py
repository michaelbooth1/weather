"""Guards: B090-K public-only retention, shared actual geo clocks and selected-leg scoring."""
from dataclasses import FrozenInstanceError
from datetime import timedelta
import json
from threading import Event
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_pilot import Clock
from tests.market.test_lfc_f2_controller import setup
from weather.market.lfc_f2_geoblock import SharedGeoblock
from weather.market.lfc_f2_post_books import PostBookRecorder
from weather.market.mm_stage2_hold import HoldEnd
from weather.market.re1_attended import Session


def journal():
    rows = []
    return SimpleNamespace(record=lambda event, **fields: rows.append({'event': event, **fields}), rows=rows)


def recording(tmp_path, *, end=7200, get=None, threaded=False):
    clock = Clock()
    band = SimpleNamespace(directory=tmp_path, condition='condition', tokens=('yes', 'no'),
        deadline=end, end=clock.now() + timedelta(seconds=end))
    calls = []
    def fetch(condition, token):
        calls.append((clock.seconds, condition, token))
        return {'bids': [], 'asks': [], 'collection_clock': clock.now().isoformat()}
    recorder = PostBookRecorder(clock=clock, max_bands=1, get=get or fetch, threaded=threaded)
    return recorder, band, clock, calls


def book_rows(tmp_path):
    return [json.loads(line) for line in (tmp_path / 'post_books.jsonl').read_text().splitlines()
            if json.loads(line)['event'] == 'post_book']


def test_public_books_every_minute_extend_on_last_event_and_bound_memory(tmp_path):
    recorder, band, clock, calls = recording(tmp_path)
    recorder.watch(band, 'fill')
    for second in range(3600):
        clock.seconds = second
        recorder.step()
    assert len(calls) == 120
    assert [time for time, _, token in calls if token == 'yes'] == list(range(0, 3600, 60))
    clock.seconds = 3600
    recorder.step()
    assert len(calls) == 120
    recorder.watch(band, 'retirement')
    recorder.step()
    clock.seconds = 7199
    recorder.step()
    clock.seconds = 7200
    recorder.step()
    assert len(calls) == 124 and len(recorder.watches) == len(recorder.journals) == 1
    rows = book_rows(tmp_path)
    assert rows[0]['collected_at_utc'] == clock.base.isoformat()
    assert rows[-1]['trigger'] == 'retirement' and rows[-1]['collected_at_utc'] != rows[0]['collected_at_utc']
    recorder.stop()


def test_public_books_stop_at_fixed_end_and_one_line_disable(tmp_path, monkeypatch):
    from weather.market import lfc_f2_post_books as module
    recorder, band, clock, calls = recording(tmp_path, end=65)
    recorder.watch(band, 'retirement')
    recorder.step()
    clock.seconds = 60
    recorder.step()
    clock.seconds = 65
    recorder.step()
    assert len(calls) == 4
    recorder.stop()
    clock.seconds = 64
    recorder.step()
    assert len(calls) == 4
    monkeypatch.setattr(module, 'POST_RETIREMENT_RECORDING', False)
    recorder, band, _, calls = recording(tmp_path / 'disabled')
    recorder.watch(band, 'fill')
    recorder.step()
    assert not calls and not recorder.watches


def test_failed_public_book_is_nonfatal_recorded_and_other_token_still_read(tmp_path):
    def fail(condition, token):
        if token == 'yes':
            raise TimeoutError('never retain raw exception text')
        return {'token': token}
    recorder, band, clock, _ = recording(tmp_path, get=fail)
    recorder.watch(band, 'fill')
    recorder.step()
    rows = book_rows(tmp_path)
    assert [row['ok'] for row in rows] == [False, True]
    assert rows[0]['exception_type'] == 'TimeoutError'
    assert 'never retain' not in (tmp_path / 'post_books.jsonl').read_text()
    recorder.stop()


def test_public_books_respect_fixed_utc_end_before_monotonic_deadline(tmp_path):
    recorder, band, clock, calls = recording(tmp_path, end=120)
    band.end = clock.now() + timedelta(seconds=30)
    recorder.watch(band, 'fill')
    recorder.step()
    clock.seconds = 60
    recorder.step()
    assert len(calls) == 2
    recorder.stop()


def test_stop_does_not_join_blocked_get_and_discards_inflight_result(tmp_path):
    entered, release = Event(), Event()
    calls = []
    def blocked(condition, token):
        calls.append(token)
        entered.set()
        assert release.wait(5)
        return {'token': token}
    recorder, band, _, _ = recording(tmp_path, get=blocked, threaded=True)
    recorder.watch(band, 'fill')
    recorder.start()
    assert entered.wait(5)
    try:
        recorder.stop()  # Would deadlock here if teardown joined the GET worker.
        assert recorder.thread.is_alive()
    finally:
        release.set()
        recorder.thread.join(5)
    assert not recorder.thread.is_alive() and calls == ['yes']
    assert not (tmp_path / 'post_books.jsonl').exists()


def test_optional_write_failure_uses_own_diagnostic_and_bounded_terminal_status(tmp_path, monkeypatch):
    from weather.market import lfc_f2_post_books as module
    recorder, band, clock, calls = recording(tmp_path / 'band')
    recorder.directory = tmp_path
    original = module.GuardedJournal
    def unavailable(path, **kwargs):
        if path.name == 'post_books.jsonl':
            raise OSError('fixture optional disk write failure')
        return original(path, **kwargs)
    monkeypatch.setattr(module, 'GuardedJournal', unavailable)
    recorder.watch(band, 'fill')
    recorder.step()
    assert len(calls) == 2 and recorder.failure['exception_type'] == 'OSError'
    rows = [json.loads(line) for line in (tmp_path / 'post_books_errors.jsonl').read_text().splitlines()]
    assert [row['event'] for row in rows] == ['opened', 'post_book_recording_unavailable', 'post_book_recording_unavailable']
    assert 'fixture optional' not in json.dumps(rows)
    monkeypatch.setattr(module, 'GuardedJournal', lambda *a, **k: (_ for _ in ()).throw(OSError()))
    recorder.diagnostics.close()
    recorder.diagnostics = None
    clock.seconds = 60
    recorder.step()
    assert len(calls) == 4 and recorder.failure['diagnostic_write_failed']
    assert len(recorder.watches) == 1 and recorder.journals == {}
    recorder.stop()


def test_recorder_start_failure_is_ancillary_and_never_spoils_money_proof(tmp_path):
    from weather.market.lfc_campaign_proof import local_money_proof
    controller, account, status, ledger, clock = setup(tmp_path)
    stopped = []
    class Unavailable:
        def start(self):
            raise RuntimeError('fixture thread failure')
        def stop(self):
            stopped.append(True)
    controller.post_books = Unavailable()
    result = controller.run()
    assert result['cleanup_ok'] and stopped and account.cancel_all_calls == [300]
    outcome = status.finish(success=True)
    proof = local_money_proof(controller.directory, ledger=ledger, session_id=controller.session_id,
                             attempt_id=controller.attempt_id, outcome=outcome)
    assert proof['complete'] and 'post_book_recording_unavailable' in proof['explained_gaps']


def test_geo_ten_bands_share_same_frozen_receipt_two_reads_per_minute():
    clock, sink = Clock(), journal()
    geo, reads = SharedGeoblock(clock, sink), []
    def fetch():
        reads.append(clock.seconds)
        return {'blocked': False}
    for second in range(180):
        clock.seconds = second
        receipts = [geo.read(fetch) for _ in range(10)]
        assert all(receipt is receipts[0] for receipt in receipts)
        assert receipts[0].collected_monotonic == 30 * (second // 30)
    assert reads == [0, 30, 60, 90, 120, 150]
    with pytest.raises(FrozenInstanceError):
        receipts[0].collected_monotonic = 179


def test_failed_geo_read_keeps_original_clock_and_late_success_is_fresh():
    clock, sink = Clock(), journal()
    geo = SharedGeoblock(clock, sink)
    original = geo.read(lambda: {'blocked': False})
    clock.seconds = 46
    def fail():
        raise TimeoutError()
    assert geo.read(fail) is original and original.collected_monotonic == 0
    clock.seconds = 76
    def late():
        clock.sleep(10)
        return {'blocked': False}
    fresh = geo.read(late)
    assert fresh.collected_monotonic == 86 and fresh.collected_at_utc == clock.now().isoformat()


@pytest.mark.parametrize('blocked', [True, None, 0, 'false'])
def test_nonpassing_shared_geoblock_ends_whole_session(tmp_path, blocked):
    controller, account, _, ledger, clock = setup(tmp_path)
    for raw in account.raws:
        raw.geography = lambda: {'blocked': blocked}
    result = controller.run()
    assert result['reason'] == 'geoblock' and result['post_count'] == 0
    assert account.cancel_all_calls == [0] and not ledger.unresolved_legs()


@pytest.mark.parametrize('selected,active,scoring,expected', [
    ((0,), {'yes': (0, '.3')}, {'yes': True}, True),
    ((1,), {'no': (1, '.6')}, {'no': True}, True),
    ((0, 1), {'yes': (0, '.3')}, {'yes': True}, False),
    ((0, 1), {'yes': (0, '.3'), 'no': (1, '.6')}, {'yes': True, 'no': False}, False),
    ((0, 1), {'yes': (0, '.3'), 'no': (1, '.6')}, {'yes': True, 'no': True}, True),
])
def test_scoring_summary_uses_selected_legs_and_keeps_each_order(selected, active, scoring, expected):
    sink = journal()
    session = SimpleNamespace(active=active, TRADE_LEGS=selected, scoring_seen=False,
        condition='condition', clock=Clock(), journal=sink,
        venue=SimpleNamespace(scoring=lambda ids: scoring),
        call=lambda name, fn: fn(), note_evidence_fault=lambda code: pytest.fail(code))
    Session.sample_scoring(session)
    assert session.scoring_seen is expected
    assert [(row['order_id'], row['scoring']) for row in sink.rows] == list(scoring.items())
