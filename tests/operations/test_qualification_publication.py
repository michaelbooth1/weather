"""Native filesystem and interruption tests for create-only record publication."""

from concurrent.futures import ThreadPoolExecutor
import errno
import os
from pathlib import Path
import subprocess

import pytest

from weather.operations.qualification import records as r


def test_atomic_publication_exposes_complete_bytes_only(tmp_path, monkeypatch):
    original = r._publish_no_replace
    observed = []
    def inspect(temporary, target):
        assert not target.exists()
        assert temporary.read_bytes() == r.encode({"status": "PASS"})
        assert target.with_name(target.name + ".claim").exists()
        observed.append(temporary)
        original(temporary, target)
    monkeypatch.setattr(r, "_publish_no_replace", inspect)
    ref = r.publish(tmp_path, "terminal.json", {"status": "PASS"})
    assert r.read(tmp_path, ref).value == {"status": "PASS"}
    assert len(observed) == 1 and not observed[0].exists()


def test_interrupted_publication_spends_claim_and_retains_partial(tmp_path, monkeypatch):
    def fail(temporary, target):
        raise OSError(errno.ENOSPC, "simulated full disk at finalization")
    monkeypatch.setattr(r, "_publish_no_replace", fail)
    with pytest.raises(OSError, match="full disk"):
        r.publish(tmp_path, "terminal.json", {"status": "PASS"})
    assert not (tmp_path / "terminal.json").exists()
    assert (tmp_path / "terminal.json.claim").exists()
    assert len(list(tmp_path.glob("*.partial"))) == 1
    with pytest.raises(FileExistsError):
        r.publish(tmp_path, "terminal.json", {"status": "PASS"})


def test_create_only_destination_is_not_overwritten(tmp_path):
    target = tmp_path / "terminal.json"
    target.write_bytes(b"preexisting evidence")
    with pytest.raises(r.QualificationError, match="already exists"):
        r.publish(tmp_path, target.name, {"status": "PASS"})
    assert target.read_bytes() == b"preexisting evidence"


def test_two_publishers_cannot_both_win(tmp_path):
    def write(value):
        try:
            return r.publish(tmp_path, "terminal.json", {"winner": value})
        except FileExistsError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, (1, 2)))
    refs = [ref for ref in results if ref is not None]
    assert len(refs) == 1
    assert r.read(tmp_path, refs[0]).value["winner"] in {1, 2}


def test_crash_after_finalization_leaves_reconcilable_bytes_not_retry(tmp_path, monkeypatch):
    original = r.read
    def fail_read(*args):
        raise OSError("simulated controller death before acknowledgment")
    monkeypatch.setattr(r, "read", fail_read)
    with pytest.raises(OSError, match="controller death"):
        r.publish(tmp_path, "terminal.json", {"status": "PASS"})
    assert (tmp_path / "terminal.json").read_bytes() == r.encode({"status": "PASS"})
    monkeypatch.setattr(r, "read", original)
    with pytest.raises(FileExistsError):
        r.publish(tmp_path, "terminal.json", {"status": "PASS"})


@pytest.mark.skipif(os.name != "nt", reason="native Windows junction; POSIX symlink covered separately")
def test_windows_junction_is_rejected_before_read_or_publication(tmp_path):
    actual, alias = tmp_path / "actual", tmp_path / "junction"
    actual.mkdir()
    (actual / "record.json").write_bytes(b"{}")
    cmd = Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe"
    result = subprocess.run([str(cmd), "/d", "/c", "mklink", "/J", str(alias), str(actual)],
                            capture_output=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    try:
        with pytest.raises(r.QualificationError, match="reparse"):
            with r.open_record(tmp_path, "junction/record.json"):
                pytest.fail("redirected content exposed")
        with pytest.raises(r.QualificationError, match="reparse"):
            r.publish(tmp_path, "junction/new.json", {"status": "PASS"})
        assert not (actual / "new.json").exists()
    finally:
        # Remove only this junction entry, never its target or a recursive tree.
        os.rmdir(alias)
