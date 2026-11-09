"""Guards: B067 bounded added closure-check cost, independent of full validation.

Synthetic no-order claims with growing retained account-read payloads. This
measures the new invariant and its incremental healthy-cache IDLE cost, not a
repeat of B066's whole campaign/private-journal workload or a money simulation.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import statistics
import time
from types import SimpleNamespace
import pytest

from tests.market.test_lfc_campaign import MAKER, Mutexes
from tests.market.test_lfc_pilot import Clock
from tests.market.test_lfc_review_b065_remeasure import bounded
from tests.market.test_lfc_review_b065_scale import fixture_writer
from weather.market import lfc_campaign_closures as closures
from weather.market.lfc_campaign import CampaignCoordinator
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_campaign_runtime import Runtime
from weather.market.lfc_campaign_state import AccountState
from weather.market.lfc_f2_breadth import example_policy
from weather.market.lfc_f2_freeze import capture
from weather.market.lfc_ledger import Ledger
from weather.market.mm_stage2_hold import digest


def timed(fn):
    cpu, wall = time.process_time(), time.perf_counter()
    result = fn()
    return {'cpu_s': time.process_time()-cpu, 'wall_s': time.perf_counter()-wall}, result


def measure(root, ledger, clock, policy, day, monkeypatch):
    def coordinator():
        state = AccountState(root/'state', ledger)
        r = Runtime(state=state, pilot_root=root, policy_path=root/'campaign.json', release={},
            clock=clock, control_root=root/'control', task_enabled=lambda: True,
            hold_path=root/'work.lock', heavy_hold_path=root/'manual-hold')
        r.lease = SimpleNamespace(check=lambda: None)
        r.notify_control = lambda row: None
        r.read_account = lambda: pytest.fail('No account read is due')
        return CampaignCoordinator(state=state, runtime=r, clock=clock, control_root=root/'control')
    c = coordinator()
    assert c.tick(lambda: policy) == 'IDLE'  # Full validation seeds the disposable manifest.
    before = ledger.previous
    invariant = AccountState(root/'state', ledger)
    cold, _ = timed(lambda: closures.check(invariant))
    warm_samples = [timed(lambda: closures.check(invariant))[0] for _ in range(5)]
    full, _ = timed(lambda: closures.check(invariant, full=True))
    baseline, actual = [], []
    for disabled, bucket in ((True, baseline), (False, actual)):
        for _ in range(3):
            c = coordinator()  # The native signature/content cache is process-local and cold.
            c.state.require_retained_evidence = lambda: pytest.fail('Healthy IDLE must reuse its established manifest')
            def without_new_invariant(state, **kwargs):
                # Measurement control only; all immutable originals are intact.
                state._closure_faults, state._closure_accepted = set(), set()
                state._closure_completed = {r['attempt_id'] for r in ledger.event_rows('autostart_close')}
                return state._closure_completed
            with monkeypatch.context() as control:
                if disabled:
                    control.setattr(closures, 'check', without_new_invariant)
                cost, result = timed(lambda: c.tick(lambda: policy))
                assert result == 'IDLE'
                bucket.append(cost)
    median = lambda rows: {key: statistics.median(r[key] for r in rows) for key in ('cpu_s', 'wall_s')}
    assert before == ledger.previous and not ledger.autostart_incidents
    return {'day': day, 'closure_count': day,
        'closure_bytes': sum(p.stat().st_size for p in invariant.root.joinpath('closed').glob('*.json')),
        'cold_invariant': cold, 'warm_invariant_median': median(warm_samples), 'full_hash_invariant': full,
        'idle_without_new_invariant_median': median(baseline), 'idle_with_new_invariant_median': median(actual),
        'idle_delta_cpu_s': median(actual)['cpu_s']-median(baseline)['cpu_s'],
        'idle_delta_wall_s': median(actual)['wall_s']-median(baseline)['wall_s'],
        'timed_idle_full_validation_calls': 0, 'tick_cadence_s': 300}


@pytest.mark.skipif(os.name != 'nt', reason='Bounded Windows NTFS/process CPU measurement')
def test_added_anchor_cost_day_one_twenty_forty(tmp_path, monkeypatch, pytestconfig):
    if not pytestconfig.getoption('--lfc-build-scale', default=False):
        pytest.skip('Explicit targeted benchmark required')
    row = example_policy(); row['enabled'] = True
    policy = parse_policy(row); clock = Clock(policy.entries[0].start)
    with bounded() as peak, account_lease(MAKER, backend=Mutexes()):
        ledger = Ledger.create(tmp_path/'ledger.jsonl', clock=clock.now, maker_address=MAKER)
        state = AccountState(tmp_path/'state', ledger); state.enroll(clock.now())
        (tmp_path/'campaign.json').write_text(json.dumps(policy.raw))
        results = []
        for day, entry in enumerate(policy.entries[:40], 1):
            with fixture_writer(ledger), monkeypatch.context() as construction:
                construction.setattr(os, 'fsync', lambda fd: None)
                construction.setattr(AccountState, 'verify', lambda self, **kw: self.read(self.root/'identity.json'))
                construction.setattr(AccountState, 'require_retained_evidence', lambda self: None)
                if entry.local_date >= '2026-11-17' and not ledger.event_rows('autostart_freeze'):
                    clock.base = datetime(2026, 11, 16, 22, 55, tzinfo=timezone.utc); clock.seconds = 0
                    capture(state, policy, clock.now())
                clock.base = entry.start; clock.seconds = 0
                claim = state.claim(entry, policy, clock.now())
                read = {'started_at_utc': clock.now().isoformat(), 'ended_at_utc': clock.now().isoformat(),
                    'positions': [], 'open_orders': [], 'trades': [],
                    # Opaque synthetic payload, not a proposed venue API field.
                    # 100 KB per date gives roughly 4 MB at day 40, below the
                    # production receipt limit and conservative vs small reads.
                    'benchmark_padding': 'x' * (100_000 * day)}
                proof = {'money_accounting_complete': True, 'cleanup_proven': True,
                    'unknown_submit': False, 'read_sha256': digest(read), 'account_read': read,
                    'ledger_head_sha256': ledger.previous}
                state.close(claim, proof, clock.now())
            if day in (1, 20, 40):
                clock.seconds = 3600
                # Reopen with the production replay, including the new anchors.
                ledger = Ledger.open(ledger.path, clock=clock.now, maker_address=MAKER)
                state = AccountState(tmp_path/'state', ledger)
                result = measure(tmp_path, ledger, clock, policy, day, monkeypatch)
                results.append(result)
                output = {'synthetic_only': True, 'at_utc': datetime.now(timezone.utc).isoformat(),
                    'scope': 'added invariant and healthy-cache IDLE delta, no inventory/private-journal workload',
                    'peak_commit_percent': peak[0], 'results': results}
                Path(r'C:\t\codex\T004\out\b067-closure-idle-cost.json').write_text(json.dumps(output, indent=2))
        assert sum(r['closure_count'] for r in results) == 61
