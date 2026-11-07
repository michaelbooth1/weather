"""Frozen one-band loop oracles, executed only against inert fixture venues.

Guards: F2 K=1 preserves the pin's opening/cleanup journal and recording-only
cadence. The latter includes the separately approved R2 minute-scoring change.
Only the old loop is supplied; current protected cleanup/quantity checks remain.
"""
import hashlib
import json
from pathlib import Path

import pytest

from tests.market.test_lfc_pilot import setup
from weather.market import re1_attended


@pytest.mark.parametrize('name,seconds', [('pin', 0), ('recording_only', 121)])
def test_K1_journal_is_byte_identical_to_frozen_loop_oracle(tmp_path, name, seconds):
    fixtures = Path(__file__).resolve().parents[1] / 'fixtures' / 'lfc_recording'
    manifest = json.loads((fixtures / 'run_oracles.json').read_bytes())
    oracle = next(row for row in manifest if row['name'] == name)
    source = (fixtures / (name + '_run.txt')).read_bytes()
    assert hashlib.sha256(source).hexdigest() == oracle['sha256']
    namespace = dict(vars(re1_attended))
    exec(compile(source, name + '_run_fixture', 'exec'), namespace)
    old, _, _, _ = setup(tmp_path / 'old')
    current, _, _, _ = setup(tmp_path / 'current')
    reference = namespace['run'](old, rehearsal_seconds=seconds)
    result = current.run(rehearsal_seconds=seconds)
    assert reference['cleanup_ok'] and result['cleanup_ok']
    assert reference['post_count'] == result['post_count'] == 2
    assert old.journal.path.read_bytes() == current.journal.path.read_bytes()
