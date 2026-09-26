from datetime import timedelta
import hashlib
import json
import pytest

from maker_core.evidence.journal import Journal, SecretGuard, write_new, verify_journal
from .fixtures.fictional_domain import T0


def test_create_only_chain_and_scrub(tmp_path):
    path = tmp_path / "journal.jsonl"
    with Journal(path, clock=lambda: T0, scope={"domain": "coin"}, guard=SecretGuard(("loaded-secret",))) as j:
        j.record("sample", payload={"Api-Key": "loaded-secret", "nested": [{"signature": "signed"}], "value": 3})
        with pytest.raises(ValueError, match="secret_output_refused"):
            j.record("bad", payload={"message": "oops loaded-secret"})
        with pytest.raises(ValueError, match="reserved"):
            j.record("bad", sequence=99)
        j.record("terminal")
    raw = path.read_bytes()
    assert b"loaded-secret" not in raw and b"signed" not in raw
    rows = verify_journal(path, expected_digest=hashlib.sha256(raw).hexdigest())
    assert len(rows) == 3 and rows[1]["payload"] == {"nested": [{}], "value": 3}
    with pytest.raises(FileExistsError):
        Journal(path, clock=lambda: T0, scope={})
    with pytest.raises(FileExistsError):
        write_new(path, {})
    new = tmp_path / "new.json"
    assert write_new(new, {"authorization": "secret", "ok": True}) == hashlib.sha256(new.read_bytes()).hexdigest()
    assert json.loads(new.read_bytes()) == {"ok": True}


@pytest.mark.parametrize("mutation", ["middle", "tail", "reorder", "newline", "whole"])
def test_tampering_refused(tmp_path, mutation):
    path = tmp_path / "chain.jsonl"
    with Journal(path, clock=lambda: T0, scope={}) as j:
        j.record("sample", value=1)
        j.record("terminal")
    original = path.read_bytes()
    lines = original.splitlines(keepends=True)
    if mutation == "middle":
        lines[1] = lines[1].replace(b'"value":1', b'"value":2')
    elif mutation == "tail":
        lines.pop()
    elif mutation == "reorder":
        lines[0], lines[1] = lines[1], lines[0]
    elif mutation == "newline":
        lines[-1] = lines[-1].rstrip()
    else:
        lines[0] = lines[0].replace(b'"scope":{}', b'"scope":{"x":1}')
    path.write_bytes(b"".join(lines))
    with pytest.raises(ValueError):
        verify_journal(path)
    with pytest.raises(ValueError):
        verify_journal(path, expected_digest=hashlib.sha256(original).hexdigest())


def test_clock_regression_and_nonfinite_refused(tmp_path):
    times = iter((T0, T0-timedelta(seconds=1), T0))
    with Journal(tmp_path / "clock", clock=lambda: next(times), scope={}) as j:
        with pytest.raises(ValueError, match="regressed"):
            j.record("bad")
        with pytest.raises(ValueError):
            j.record("bad", value=float("nan"))


def test_guard_escaped_secrets_and_keys():
    guard = SecretGuard(('quote"\\sensitive',))
    with pytest.raises(ValueError, match="secret_output_refused"):
        guard.clean({"message": 'quote"\\sensitive'})
    with pytest.raises(ValueError, match="secret_output_refused"):
        guard.clean({'quote"\\sensitive': "value"})
