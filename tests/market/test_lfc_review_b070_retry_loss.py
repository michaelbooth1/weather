"""Guards: a visible closure retry must not forget its published original."""
import json
import uuid
from datetime import timedelta
from pathlib import Path
import pytest

from tests.market.test_lfc_campaign import MAKER, Mutexes
from tests.market.test_lfc_review_b069_retry import interrupted, coordinator
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_state import AccountState
from weather.market.lfc_campaign_control import latest_control, watch_status
from weather.market.lfc_ledger import Ledger
from weather.market.mm_stage2_hold import canonical_bytes


@pytest.mark.parametrize('cold', [False, True])
@pytest.mark.parametrize('change', ['deleted', 'valid_changed'])
def test_pending_retry_preserves_original_identity_between_ticks(tmp_path, monkeypatch, cold, change):
    with account_lease(MAKER, backend=Mutexes()):
        runtime, policy, claim, path, original = interrupted(tmp_path, monkeypatch)
        ledger_path = runtime.state.ledger.path
        ordinary = Path.open
        def fail(p, mode='r', *a, **kw):
            if p == ledger_path and mode == 'ab':
                raise OSError('temporary_append_failure')
            return ordinary(p, mode, *a, **kw)
        with monkeypatch.context() as failure:
            failure.setattr(Path, 'open', fail)
            assert coordinator(runtime).tick(lambda: policy) == 'RETRY_PENDING'
        assert watch_status(latest_control(runtime.control_root), now=runtime.clock.now())[1] == 1
        assert not runtime.state.ledger.event_rows('autostart_close')
        if change == 'deleted':
            path.unlink()
        else:
            row = json.loads(original)
            row['closed_at_utc'] = (runtime.clock.now()+timedelta(seconds=1)).isoformat()
            path.write_bytes(canonical_bytes(row))
        changed = path.read_bytes() if path.exists() else None
        if cold:
            runtime.state = AccountState(runtime.state.root.parent, Ledger.open(ledger_path, clock=runtime.clock.now))
        runtime.clock.sleep(2)
        first = coordinator(runtime).tick(lambda: policy)
        runtime.clock.sleep(1)
        second = coordinator(runtime).tick(lambda: policy)
        evidence = {
            'cold': cold, 'change': change, 'first': first, 'second': second,
            'incidents': runtime.state.ledger.autostart_incidents,
            'anchors': runtime.state.ledger.event_rows('autostart_close'),
            'control': latest_control(runtime.control_root),
            'original_preserved': path.exists() and path.read_bytes() == original,
        }
        output = tmp_path/('r7-retry-loss-'+uuid.uuid4().hex)
        output.mkdir()
        (output/'observed.json').write_text(json.dumps(evidence, sort_keys=True))
        (output/'original.json').write_bytes(original)
        if changed is not None: (output/'changed.json').write_bytes(changed)
        if path.exists(): (output/'after.json').write_bytes(path.read_bytes())
        (output/'ledger.jsonl').write_bytes(ledger_path.read_bytes())
        assert first == 'INCIDENT' and second == 'INCIDENT', evidence
        assert len(runtime.state.ledger.autostart_incidents) == 1
        assert not runtime.state.ledger.event_rows('autostart_close')
        assert path.read_bytes() == changed if changed is not None else not path.exists()
