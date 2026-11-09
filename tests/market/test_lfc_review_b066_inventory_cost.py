"""Guards: B066 measures cold idle validation with real, proved held inventory.

Reuse a verified synthetic prefix at its bound original path. Only the final
session changes: twelve paired bands fill and retain their T+1 lots. No money
gate, validation rule, source adapter or idle shortcut is changed or bypassed
during measurement. Construction uses the existing bounded rehearsal helpers.
"""
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
import zipfile
import pytest

from tests.market.test_lfc_campaign import Mutexes
from tests.market.test_lfc_f2_breadth import cities
from tests.market.test_lfc_f2_controller import Account, MAKER, setup
from tests.market.test_lfc_f2_repost import FundedRaw
from tests.market.test_lfc_pilot import Clock
from tests.market.test_lfc_review_b065_archive import hashed
from tests.market.test_lfc_review_b065_remeasure import bounded
from tests.market.test_lfc_review_b065_scale import fixture_writer, padding
from weather.market.lfc_campaign import CampaignCoordinator
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import load_policy
from weather.market.lfc_campaign_proof import local_money_proof
from weather.market.lfc_campaign_runtime import Runtime
from weather.market.lfc_campaign_state import AccountState
from weather.market.lfc_capital import CapitalBook
from weather.market.lfc_ledger import Ledger
from weather.market.mm_stage2_hold import HoldEnd, digest
from weather.operations.live_path_security import validate_nonreparse_directory


class HeldAccount(Account):
    def advance(self):
        if self.clock.seconds >= 12:
            for raw in self.raws:
                for row in raw.memory.orders.values():
                    if row['status'] == 'LIVE':
                        row.update(status='MATCHED', size_matched=row['original_size'],
                                   associate_trades=['fill-' + row['id']])
        super().advance()


def restore_prefix(pytestconfig, day):
    argument = pytestconfig.getoption('--lfc-existing-scale', default=None)
    archive_argument = pytestconfig.getoption('--lfc-scale-archive', default=None)
    if not argument or not archive_argument:
        pytest.skip('Explicit retained, test-owned synthetic archive required')
    root = Path(argument).resolve(strict=True)
    assert root.is_relative_to(Path(r'C:\t\codex\T004\pt'))
    assert root.name.startswith('test_day_one_twenty_forty_fina')
    validate_nonreparse_directory(root)
    assert not any(p.is_file() for p in root.rglob('*')), 'Archive current synthetic leaves first'
    source = Path(archive_argument).resolve(strict=True)
    assert source.parent == Path(r'C:\t\codex\T004\out')
    manifest = json.loads(source.with_suffix('.json').read_text())
    assert manifest['synthetic_only'] is True and Path(manifest['source_root']) == root
    with source.open('rb') as stream:
        assert hashed(stream) == manifest['archive_sha256']
    prefix, rows, count = [], [], 0
    with zipfile.ZipFile(source) as archive:
        with archive.open('ledger.jsonl') as stream:
            for line in stream:
                assert len(line) < 2 * 1024**2
                row = json.loads(line)
                count += row['event'] == 'autostart_claim'
                if count == day and row['event'] == 'autostart_claim':
                    break
                prefix.append(line); rows.append(row)
        assert rows[0]['maker_address'].lower() == MAKER.lower()
        enrollment = next(r for r in rows if r['event'] == 'autostart_enroll')
        state_root = Path(enrollment['state_root']).relative_to(root).as_posix()
        wanted = {'campaign.json', state_root + '/identity.json'}
        private = []
        for row in rows:
            if row['event'] == 'baseline':
                wanted.add(row['file'])
            elif row['event'] == 'autostart_freeze':
                wanted.add(state_root + '/policies/freeze.json')
            elif row['event'] == 'autostart_claim':
                aid = row['attempt_id']
                wanted.update({state_root+'/claims/'+row['local_date']+'.json',
                    state_root+'/policies/'+aid+'.json', state_root+'/results/'+aid+'.json',
                    state_root+'/closed/'+aid+'.json'})
                result = json.loads(archive.read(state_root+'/results/'+aid+'.json'))
                private.append(result['private_evidence_directory'] + '/')
        wanted.update(n for n in archive.namelist() if any(n.startswith(p) for p in private))
        for name in sorted(wanted):
            relative = Path(name)
            assert not relative.is_absolute() and '..' not in relative.parts
            assert not any(p.startswith('.env') for p in relative.parts)
            assert relative.suffix not in {'.key', '.cred', '.pem'}
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            validate_nonreparse_directory(target.parent)
            sha, size = hashlib.sha256(), 0
            with archive.open(name) as stream, target.open('xb') as output:
                for block in iter(lambda: stream.read(1024*1024), b''):
                    output.write(block); sha.update(block); size += len(block)
            assert {'sha256': sha.hexdigest(), 'bytes': size} == manifest['verified_members'][name]
    with (root/'ledger.jsonl').open('xb') as stream:
        for line in prefix:
            stream.write(line)
    return root


def runtime(root, state, clock):
    value = Runtime(state=state, pilot_root=root, policy_path=root/'campaign.json',
        release={}, clock=clock, control_root=root/'control', task_enabled=lambda: True,
        hold_path=root/'work.lock', heavy_hold_path=root/'manual-hold')
    value.lease = SimpleNamespace(check=lambda: None)
    value.notify_control = lambda row: None
    value.read_account = lambda: pytest.fail('Nothing is due; no account read allowed')
    return value


def measured(fn):
    cpu, wall = time.process_time(), time.perf_counter()
    result = fn()
    return {'cpu_seconds': time.process_time()-cpu, 'wall_seconds': time.perf_counter()-wall}, result


@pytest.mark.parametrize('day', [1, 20, 40])
@pytest.mark.skipif(os.name != 'nt', reason='Windows bounded campaign-scale measurement')
def test_cold_idle_tick_with_held_t1_inventory(day, pytestconfig, monkeypatch, record_property):
    with bounded() as peak, account_lease(MAKER, backend=Mutexes()):
        root = restore_prefix(pytestconfig, day)
        policy = load_policy(root/'campaign.json'); entry = policy.entries[day-1]
        clock = Clock(entry.start)
        ledger = Ledger.open(root/'ledger.jsonl', clock=clock.now, maker_address=MAKER)
        state = AccountState(root/'state', ledger)
        state.verify(); assert len(state.claims()) == day-1 and not state.pending()
        # The prior immutable prefix is checked above and again cold below.
        # Fixture-only fast writes avoid measuring hundreds of durable SSD
        # flushes. No gate or retained verification is replaced.
        with fixture_writer(ledger), monkeypatch.context() as building:
            building.setattr(os, 'fsync', lambda fd: None)
            controller, account, status, ledger, clock = setup(root, k=12, enrolled=True,
                shared_ledger=ledger, shared_state=state, base=entry.start,
                policy_row=policy.raw, universe_rows=cities(entry.start),
                session_id='B066-held-'+str(day), account_type=HeldAccount, raw_type=FundedRaw)
            claim = account.claim
            # Keep the earlier benchmark's six-hour observation floor. The
            # actual final session stops after its fills; extra observations
            # deliberately overstate, rather than hide, retained read cost.
            padding(controller.journal, ((kind, {}) for _ in range(4320)
                for kind in ('heartbeat_request', 'heartbeat_response')))
            for band in controller.bands:
                snapshot = band.venue.raw.memory.public_input
                padding(band.journal, (('market_snapshot', {'snapshot': snapshot}) for _ in range(360)))
            def stop_repost(band):
                raise HoldEnd('fixture_inventory_hold')
            controller.repost_proof = stop_repost
            result = controller.run()
            assert result['cleanup_ok'] and result['post_count'] == 24, result
            outcome = status.finish(success=True)
            local = local_money_proof(controller.directory, ledger=ledger,
                session_id=controller.session_id, attempt_id=claim['attempt_id'], outcome=outcome)
            assert local['complete'] and not local['unknown_submit'], local
            r = runtime(root, state, clock)
            r.save_result(claim, {'session_id': controller.session_id, 'outcome': outcome,
                'evidence_complete': True, 'inventory_proven': True, 'unknown_submit': False,
                'local_money_proof': local, 'private_evidence_directory': controller.directory.name})
            _, sha, retained = state.retained_result(claim)
            state.close(claim, {'money_accounting_complete': True, 'cleanup_proven': True,
                'unknown_submit': False, 'result_sha256': sha,
                'private_evidence_sha256': digest(retained)}, clock.now())
        clock.seconds = 3600
        state.save('followups/B066-held-'+str(day)+'.json', {
            'observed_at_utc': clock.now().isoformat(), 'gaps': [],
            'monetary_action': False, 'money_proof_complete': True})
        # A genuinely cold scheduled process: neither ledger nor proof cache
        # survives. Include replay separately so CPU/tick is not understated.
        load_cost, ledger = measured(lambda: Ledger.open(root/'ledger.jsonl', clock=clock.now, maker_address=MAKER))
        state = AccountState(root/'state', ledger)
        r = runtime(root, state, clock)
        assert not r.followup_due(policy)
        coordinator = CampaignCoordinator(state=state, runtime=r, clock=clock,
            control_root=root/'control', followup=r.followup)
        from weather.market.lfc_campaign_idle import eligible
        figures = CapitalBook(ledger).figures()
        assert figures['unrecovered_inventory_cost_native'] > 200_000_000
        assert figures['resting_reserve_native'] == 0 and not ledger.unresolved_legs()
        assert not eligible(coordinator, policy)
        before = len(ledger.rows)
        tick_cost, result = measured(lambda: coordinator.tick(lambda: policy))
        assert result == 'IDLE' and len(ledger.rows) == before
        assert not state.incidents() and not state.pending()
        measurement = {'day': day, 'date': entry.local_date, 'ledger_rows': before,
            'claims': day, 'bands': 12, 'inventory_basis_native': figures['unrecovered_inventory_cost_native'],
            'cold_ledger_load': load_cost, 'idle_tick': tick_cost,
            'total_cpu_seconds': load_cost['cpu_seconds']+tick_cost['cpu_seconds'],
            'tick_cadence_seconds': 300, 'full_validation': True,
            'peak_commit_percent': peak[0], 'synthetic_only': True}
        target = Path(r'C:\t\codex\T004\out')/('b066-held-inventory-day-'+str(day)+'.json')
        target.write_text(json.dumps(measurement, indent=2))
        record_property('held_inventory_metrics', json.dumps(measurement))
        print(json.dumps(measurement), flush=True)
