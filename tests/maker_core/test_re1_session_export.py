"""Guard failures never print values or silently scrub a source into a pass."""
from copy import deepcopy
from pathlib import Path
import pytest

from maker_core.evidence.journal import canonical_bytes
from .fixtures.re1_session_export import check_secrets, read_guarded


@pytest.mark.parametrize('field', ['api_key', 'signature', 'privateKey', 'credentials', 'session_key', 'password'])
def test_sensitive_field_stops_without_value(field):
    with pytest.raises(ValueError, match='STOP') as caught:
        check_secrets({field: 'do-not-display-this-value'})
    assert 'do-not-display' not in str(caught.value)


def test_lifecycle_identifier_exception_requires_exact_adapter_structure():
    row = dict(lifecycle_key='order-example', order_id='order-example',
               source='polymarket_global_user_ws', official_event_type='order')
    check_secrets(row)
    for field in ('order_id', 'source', 'official_event_type'):
        modified = deepcopy(row)
        modified[field] = 'wrong'
        with pytest.raises(ValueError, match='STOP'):
            check_secrets(modified)


def test_forbidden_filename_rejected_before_open(monkeypatch, tmp_path):
    def forbidden(*a, **kw):
        raise AssertionError('forbidden path was opened')
    monkeypatch.setattr(Path, 'open', forbidden)
    for name in ('.env', 'key.json', 'credentials.json', 'selection.json'):
        with pytest.raises(ValueError, match='only explicit session journal'):
            read_guarded(tmp_path / 'session-1' / name)


def test_guard_precedes_chain_validation_and_never_returns_partial_projection(tmp_path):
    path = tmp_path / 'session-1' / 'journal.jsonl'
    path.parent.mkdir()
    path.write_bytes(canonical_bytes(dict(api_key='do-not-display', sequence=999)))
    with pytest.raises(ValueError, match='STOP'):
        read_guarded(path)


def test_chain_mismatch_refuses(tmp_path):
    path = tmp_path / 'session-1' / 'journal.jsonl'
    path.parent.mkdir()
    path.write_bytes(canonical_bytes(dict(event='opened', sequence=0, previous_sha256='wrong')))
    with pytest.raises(ValueError, match='hash chain'):
        read_guarded(path)
