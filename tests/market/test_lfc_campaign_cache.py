"""Immutable-cache and capital-replay boundaries, using synthetic files only.

Guards: B046 C4; caching never hides changed, missing or rejected evidence.
"""
import os

import pytest

from tests.market.test_lfc_f2_capital import ledger_at, install, filled, activity
from weather.market.lfc_capital import CapitalBook, record_activity
from weather.market.lfc_ledger import Ledger, LedgerUnavailable
from weather.market.lfc_retained_cache import RetainedCache


def test_same_length_change_with_restored_mtime_invalidates_cached_sha(tmp_path):
    path = tmp_path / 'retained.json'
    path.write_text('{"a":1}')
    cache = RetainedCache()
    for n in range(20):
        before, stamp = cache.sha(path), path.stat()
        path.write_text('{"a":' + str(n % 2 + 2) + '}')
        os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        assert path.stat().st_size == stamp.st_size
        assert cache.sha(path) != before
        path.write_text('{"a":1}')
    path.write_text('{"a":2}')
    assert cache.json(path) == {'a': 2}


def test_unavailable_native_change_sequence_uses_full_reads_without_cached_proof(tmp_path, monkeypatch):
    from weather.market import lfc_retained_cache as module
    monkeypatch.setattr(module, 'change_stamp', lambda *a: None)
    path = tmp_path / 'retained.json'; path.write_text('{"a":1}')
    cache = RetainedCache(); before = cache.sha(path); stamp = path.stat()
    path.write_text('{"a":2}'); os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert cache.sha(path) != before and cache.json(path) == {'a': 2}
    assert cache.memo('key', lambda: 1, cacheable=False) == 1
    assert cache.memo('key', lambda: 2, cacheable=False) == 2


def test_cached_results_are_detached_and_missing_files_never_return_old_proof(tmp_path):
    path = tmp_path / 'retained.json'; path.write_text('{"a":[]}')
    cache = RetainedCache()
    first = cache.json(path); first['a'].append('changed')
    assert cache.json(path) == {'a': []}
    cache.sha(path); path.unlink()
    with pytest.raises((OSError, RuntimeError)): cache.sha(path)
    with pytest.raises((OSError, RuntimeError)): cache.json(path)


def test_replacement_and_reboot_revalidate_the_actual_artifact(tmp_path):
    path = tmp_path / 'retained.json'; path.write_text('{"a":1}')
    cache = RetainedCache(); first = cache.sha(path)
    replacement = tmp_path / 'replacement.json'; replacement.write_text('{"a":2}')
    stamp = path.stat(); os.utime(replacement, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    replacement.replace(path)
    assert cache.sha(path) != first
    assert RetainedCache().sha(path) == cache.sha(path)


def test_capital_checkpoint_is_detached_and_rejected_events_cannot_credit_it(tmp_path):
    ledger = ledger_at(tmp_path); filled(ledger, 'lot'); install(ledger)
    expected = CapitalBook(ledger).figures()
    detached = CapitalBook(ledger)
    detached.lots.clear(); detached.losses = -1000000000
    assert CapitalBook(ledger).figures() == expected
    before = ledger.path.read_bytes()
    with pytest.raises(LedgerUnavailable): ledger.record('capital_cost', amount_native=-1, reason='fixture')
    assert ledger.path.read_bytes() == before
    assert CapitalBook(ledger).figures() == expected
    record_activity(ledger, activity(cash='15'))
    assert CapitalBook(ledger).figures() == CapitalBook(Ledger.open(ledger.path, clock=ledger.clock)).figures()


def test_cold_ledger_open_rejects_chain_changes_despite_a_warm_row_hash_cache(tmp_path):
    ledger = ledger_at(tmp_path); install(ledger)
    ledger.row_sha256(0)
    raw = ledger.path.read_bytes()
    ledger.path.write_bytes(raw.replace(b'"budget_pusd":"100"', b'"budget_pusd":"101"', 1))
    with pytest.raises(LedgerUnavailable): Ledger.open(ledger.path, clock=ledger.clock)
    with pytest.raises(LedgerUnavailable): ledger.record('halt', reason='fixture')
