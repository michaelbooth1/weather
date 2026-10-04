from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import os

import pytest

from weather.operations import compress_on_close as subject
from weather.operations.ntfs_file_compression import MIB, LockedNtfsFile
from weather.schema_registry import schema_version

NOW = datetime(2026, 9, 26, 5, tzinfo=timezone.utc)


def test_market_local_close_and_large_token_eligibility():
    assert subject.closed(Path("highest-temperature-in-toronto-on-september-25-2026"), NOW)
    assert not subject.closed(Path("highest-temperature-in-los-angeles-on-september-25-2026"), NOW)
    row = SimpleNamespace(st_size=81 * MIB, st_mtime=NOW.timestamp() - 7201, st_file_attributes=32)
    assert subject.eligible(row, NOW)
    for update in ({"st_size": 256 * MIB + 1}, {"st_mtime": NOW.timestamp()}, {"st_file_attributes": 0x800}):
        assert not subject.eligible(SimpleNamespace(**{**vars(row), **update}), NOW)
    with pytest.raises(ValueError, match="bounded"):
        LockedNtfsFile(Path("unused"), writable=True, max_file_bytes=257 * MIB)


def test_expiring_exact_host_policy(tmp_path):
    policy = {"schema_version": schema_version("compress_on_close_policy"),
              "production_repo_root": str(tmp_path), "execution_host_id": "a" * 64,
              "operation": "compress_and_retain", "approved_by": "fixture owner",
              "approved_at_utc": (NOW - timedelta(minutes=1)).isoformat(),
              "expires_at_utc": (NOW + timedelta(hours=1)).isoformat(), "max_bytes": 81 * MIB}
    assert subject.validate_policy(policy, tmp_path, NOW) == 81 * MIB
    for update in ({"max_bytes": 2**30 + 1}, {"max_bytes": True}, {"execution_host_id": ""},
                   {"approved_by": ""}, {"expires_at_utc": NOW.isoformat()}, {"operation": "delete"}):
        with pytest.raises(ValueError):
            subject.validate_policy({**policy, **update}, tmp_path, NOW)


def test_busy_writer_prevents_even_metadata_reads(tmp_path, monkeypatch):
    path = tmp_path / "data/snapshots/highest-temperature-in-toronto-on-september-25-2026/clob_tokens.jsonl"
    monkeypatch.setattr(subject, "acquire_writer_lock", lambda *a, **k: None)
    with pytest.raises(ValueError, match="writer"):
        subject.compress_released(path, tmp_path, now=NOW, remaining=2**30,
                                  apply=True, guard=lambda: None, journal=lambda *a: None)


@pytest.mark.skipif(os.name != "nt", reason="native retained-byte verification")
@pytest.mark.parametrize("name,mib", [("clob_tokens.jsonl", 81), ("clob_tokens.csv", 1)])
def test_native_large_token_file_retains_path_hash_and_mtime(tmp_path, name, mib):
    from weather.io import sha256_file
    path = tmp_path / "data/snapshots/highest-temperature-in-toronto-on-september-25-2026" / name
    path.parent.mkdir(parents=True)
    with path.open("wb") as stream:
        for _ in range(mib):
            stream.write(b"a" * MIB)
    stamp = int((NOW - timedelta(hours=3)).timestamp())
    os.utime(path, (stamp, stamp))
    before_hash, before = sha256_file(path), path.stat()
    journal = []
    result, processed = subject.compress_released(path, tmp_path, now=NOW, remaining=2**30,
        apply=True, guard=lambda: None, journal=lambda phase, row: journal.append((phase, row)))
    assert processed == mib * MIB
    assert result["status"] == "VERIFIED" and result["reclaimed_bytes"] > 0
    assert sha256_file(path) == before_hash
    assert (path.stat().st_ino, path.stat().st_mtime_ns) == (before.st_ino, before.st_mtime_ns)
    assert [phase for phase, _ in journal] == ["before", "after"]
