"""Guards: B065 reruns reuse retained synthetic bytes instead of duplicating a campaign.

An explicit argument, task-folder containment, fake maker and forty closed
claims are required. The full verifier remains in every measured phase.
"""
from contextlib import contextmanager
from datetime import datetime
import json
import os
from pathlib import Path
import threading
import time
import cProfile
import pstats
import io
import pytest

from tests.market.test_lfc_campaign import Mutexes
from tests.market.test_lfc_f2_capital import MAKER
from tests.market.test_lfc_pilot import Clock
from tests.market.test_lfc_review_b065_scale import measure
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import load_policy
from weather.market.lfc_campaign_runtime import Runtime
from weather.market.lfc_campaign_state import AccountState
from weather.market.lfc_ledger import Ledger
from weather.operations.live_path_security import validate_nonreparse_directory


@contextmanager
def bounded():
    stop = threading.Event(); began = time.perf_counter(); peak = [0.0]
    def watch():
        import ctypes
        class Memory(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in ('ram', 'ram_free', 'commit', 'commit_free', 'virtual', 'virtual_free', 'extended')]
        while not stop.wait(1):
            mem = Memory(); mem.length = ctypes.sizeof(mem)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)) or not mem.commit:
                os._exit(125)
            used = (mem.commit-mem.commit_free)/mem.commit
            peak[0] = max(peak[0], used*100)
            if used >= .85 or time.perf_counter()-began > 570:
                os._exit(124)
    thread = threading.Thread(target=watch, daemon=True); thread.start()
    try: yield peak
    finally: stop.set(); thread.join(timeout=2)


@pytest.mark.skipif(os.name != 'nt', reason='Explicit Windows synthetic workload')
def test_remeasure_existing_forty_day_fixture(pytestconfig, tmp_path, monkeypatch, record_property):
    argument = pytestconfig.getoption('--lfc-existing-scale', default=None)
    if not argument:
        pytest.skip('Explicit retained synthetic fixture required')
    root = Path(argument).resolve(strict=True)
    allowed = Path(r'C:\t\codex\T004\pt').resolve(strict=True)
    assert root.is_relative_to(allowed)
    validate_nonreparse_directory(root)
    policy = load_policy(root/'campaign.json')
    assert policy.f2 and policy.raw['max_session_seconds'] == 300
    clock = Clock(policy.entries[39].start); clock.seconds = 300
    with bounded() as peak, account_lease(MAKER, backend=Mutexes()):
        ledger = Ledger.open(root/'ledger.jsonl', clock=clock.now, maker_address=MAKER)
        assert len(ledger.autostart_claims) == len(ledger.autostart_results) == 40
        assert not ledger.open_sessions() and not ledger.unresolved_legs()
        assert len([r for r in ledger.capital_rows if r['event']=='capital_native_group']) == 40
        assert len([r for r in ledger.capital_rows if r['event']=='capital_activity']) == 40
        state = AccountState(root/'state', ledger)
        state.verify(); assert not state.pending() and not state.incidents()
        actual = Runtime.pre_go
        def next_fresh_baseline(self, entry, selected_policy):
            # Existing immutable baselines are retained. Simulate another
            # permitted start second, then call the unmodified real method.
            latest = max(datetime.fromisoformat(r['at_utc']) for r in self.state.ledger.baselines)
            self.clock.seconds = max(1, int((latest-entry.start).total_seconds())+1)
            return actual(self, entry, selected_policy)
        monkeypatch.setattr(Runtime, 'pre_go', next_fresh_baseline)
        result, _ = measure(root, ledger, policy, clock, monkeypatch, 40)
        result['peak_commit_percent'] = peak[0]
        (tmp_path/'metrics.json').write_text(json.dumps(result, indent=2))
        record_property('scale_metrics', json.dumps(result))


@pytest.mark.skipif(os.name != 'nt', reason='Explicit Windows synthetic workload')
def test_profile_existing_verify_without_rebuilding_inputs(pytestconfig, tmp_path, record_property):
    argument = pytestconfig.getoption('--lfc-existing-scale', default=None)
    if not argument: pytest.skip('Explicit retained synthetic fixture required')
    root = Path(argument).resolve(strict=True)
    assert root.is_relative_to(Path(r'C:\t\codex\T004\pt').resolve(strict=True))
    validate_nonreparse_directory(root)
    with bounded() as peak, account_lease(MAKER, backend=Mutexes()):
        clock = Clock()
        state = AccountState(root/'state', Ledger.open(root/'ledger.jsonl',clock=clock.now,maker_address=MAKER))
        assert len(state.ledger.autostart_claims)==40
        profiler=cProfile.Profile(); began=time.perf_counter(); profiler.runcall(state.verify)
        elapsed=[time.perf_counter()-began]
        output=io.StringIO(); pstats.Stats(profiler,stream=output).sort_stats('cumulative').print_stats(25)
        record_property('cold_profile', output.getvalue())
        for _ in range(2):
            began=time.perf_counter(); state.verify(); elapsed.append(time.perf_counter()-began)
        profiler=cProfile.Profile(); profiler.runcall(state.verify)
        output=io.StringIO(); pstats.Stats(profiler,stream=output).sort_stats('cumulative').print_stats(25)
        (tmp_path/'profile.txt').write_text(output.getvalue())
        record_property('verify_seconds', json.dumps(elapsed))
