"""Read-only follow-ups remain independent and never rewrite an outcome.

Guards: B036 D+1/D+2 independence, bounded ancillary work and later measured facts.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from tests.market.test_lfc_campaign import Mutexes
from tests.market.test_lfc_f2_capital import MAKER
from tests.market.test_lfc_f2_controller import setup
from tests.market.test_lfc_f2_evidence import runtime_at_controller
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_proof import local_money_proof
from weather.market.lfc_f2_economics import publish_supplements
from weather.market.lfc_f2_followup import collect, maintenance
from weather.market.lfc_recording_io import file_sha, strict_json


def test_failed_D1_does_not_block_D2_or_net_rebate_and_calls_are_bounded(tmp_path, monkeypatch):
    from weather.market import lfc_settlement_record as settlements, lfc_rewards_record as rewards
    from tests.market.test_lfc_pilot import Clock
    clock = Clock(datetime(2026, 11, 13, 18, tzinfo=timezone.utc))
    starts = ['2026-11-12T14:00:00+00:00', '2026-11-11T14:00:00+00:00']
    sessions = {str(i): {'start': {'condition_id': 'c' + str(i), 'recorded_at_utc': stamp},
                        'end': {}, 'legs': [str(i)]} for i, stamp in enumerate(starts)}
    ledger = SimpleNamespace(sessions=sessions, legs={str(i): {'token_id': str(i)} for i in range(2)})
    runtime = SimpleNamespace(clock=clock, pilot_root=tmp_path, state=SimpleNamespace(ledger=ledger, maker=MAKER))
    calls = []
    monkeypatch.setattr(settlements, 'record_settlement', lambda *a, **kw: {'terminal': False})
    monkeypatch.setattr(rewards, 'latest_record', lambda *a, **kw: (None, None, -1))
    def reward(root, day, **kw):
        calls.append(('reward', day))
        if day == '2026-11-12':
            raise TimeoutError('fixture D1 incomplete')
        kw['get']('/v2/activity', {})
    monkeypatch.setattr(rewards, 'record_rewards', reward)
    monkeypatch.setattr(rewards, 'record_rebates', lambda root, day, **kw: calls.append(('rebate', day)))
    reads = []
    def get(*args):
        reads.append(clock.monotonic())
        return b'{}'
    row = collect(runtime, get=get, reward_client=SimpleNamespace())
    assert ('reward', '2026-11-11') in calls and ('rebate', '2026-11-12') in calls
    assert row['gaps'] == ['d1_reward_TimeoutError'] and row['monetary_action'] is False


def test_maintenance_near_start_has_no_read_or_date_claim(tmp_path):
    from weather.market.lfc_campaign_policy import parse_policy
    from weather.market.lfc_f2_policy import example_policy
    from tests.market.test_lfc_pilot import Clock
    policy = parse_policy(example_policy())
    clock = Clock(policy.entries[0].start - timedelta(minutes=10))
    maintenance(SimpleNamespace(clock=clock), policy)


def test_R3_shared_read_context_never_retains_unused_key_or_reader_token():
    from weather.market.lfc_campaign_runtime import reward_context
    fields = {key: key + '_fixture' for key in ('PRIVATE_KEY', 'READER_TOKEN', 'API_KEY', 'API_SECRET',
                                               'API_PASSPHRASE', 'WALLET_ADDRESS', 'FUNDER_ADDRESS')}
    fields['SIGNATURE_TYPE'] = '3'
    selected, guard, kind = reward_context(fields)
    assert set(selected) == {'API_KEY', 'API_SECRET', 'API_PASSPHRASE', 'WALLET_ADDRESS', 'FUNDER_ADDRESS'}
    assert kind == 3 and fields['PRIVATE_KEY'] not in vars(guard).values()
    assert fields['PRIVATE_KEY'] not in repr(vars(guard)) and fields['READER_TOKEN'] not in repr(vars(guard))


def test_hourly_maintenance_refreshes_cash_and_preserves_transient_gaps(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from tests.market.test_lfc_pilot import Clock
    from weather.market import lfc_f2_followup as followup, lfc_f2_economics as economics
    from weather.market.lfc_campaign_policy import parse_policy
    from weather.market.lfc_f2_policy import example_policy
    from weather.market.lfc_recording_io import write_new
    clock = Clock(datetime(2026, 11, 13, 22, tzinfo=timezone.utc))
    saved, reads, posts = [], [], []
    class State:
        root, ledger = tmp_path, object()
        def read(self, path): return strict_json(path.read_bytes())
        def require_retained_evidence(self): pass
        def save(self, relative, row):
            saved.append(row)
            write_new(self.root / relative, {'schema_version': 'fixture', **row})
    @contextmanager
    def admission():
        yield
    def read():
        reads.append(clock.monotonic())
        if len(reads) == 2:
            raise TimeoutError('fixture gap')
        return {}
    runtime = SimpleNamespace(clock=clock, state=State(), admission=admission, reload_ledger=lambda: None,
        read_account=read, core_proof=lambda *a: {'unknown_submit': False, 'money_contradiction': False})
    monkeypatch.setattr(followup, 'collect', lambda r: {'observed_at_utc': clock.now().isoformat(),
        'observations': [], 'gaps': [], 'monetary_action': False})
    monkeypatch.setattr(economics, 'publish_supplements', lambda r: posts.append(clock.monotonic()))
    policy = parse_policy(example_policy())
    maintenance(runtime, policy)
    maintenance(runtime, policy)
    assert len(reads) == len(posts) == 1
    clock.sleep(3601)
    maintenance(runtime, policy)
    assert len(reads) == len(posts) == 2
    assert saved[-1]['gaps'] == ['cash_followup_TimeoutError']
    assert not list((tmp_path / 'claims').glob('*.json'))


def test_supplement_is_create_only_keeps_original_and_missing_original_takes_N1_path(tmp_path, monkeypatch):
    from weather.market.lfc_campaign_state import StateRefused
    import pytest
    with account_lease(MAKER, backend=Mutexes()):
        controller, account, status, ledger, clock = setup(tmp_path, enrolled=True)
        controller.run()
        outcome = status.finish(success=True)
        runtime = runtime_at_controller(controller, account, status, ledger, clock, monkeypatch)
        local = local_money_proof(controller.directory, ledger=ledger, session_id=controller.session_id,
                                 attempt_id=controller.attempt_id, outcome=outcome)
        runtime.save_result(account.claim, {'session_id': controller.session_id, 'outcome': outcome,
            'private_evidence_directory': controller.directory.relative_to(tmp_path).as_posix(),
            'unknown_submit': False, 'evidence_complete': True, 'inventory_proven': True, 'local_money_proof': local})
        original = file_sha(status.directory / (controller.session_id + '.json'))
        publish_supplements(runtime)
        files = list(runtime.control_root.parent.glob(controller.session_id + '.e-*.json'))
        assert len(files) == 1
        body = strict_json(files[0].read_bytes())
        assert body['measured']['rewards']['actually_paid_native'] is None
        assert body['measured']['rewards']['evidence_gaps']
        assert 'PLANNING' not in files[0].read_text()
        publish_supplements(runtime)
        assert len(list(runtime.control_root.parent.glob(controller.session_id + '.e-*.json'))) == 1
        assert file_sha(status.directory / (controller.session_id + '.json')) == original
        (controller.bands[0].directory / 'journal.jsonl').unlink()
        with pytest.raises(StateRefused):
            publish_supplements(runtime)
        assert runtime.state.incidents()
