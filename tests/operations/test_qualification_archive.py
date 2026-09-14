"""Actual ZIP containers: path, mode, size, substitution and spent-root faults."""

import hashlib
import stat
import zipfile

import pytest

from weather.operations.qualification import archive
from weather.operations.qualification.records import QualificationError


def bundle(tmp_path, members):
    path = tmp_path / "evidence.zip"
    with zipfile.ZipFile(path, "w") as output:
        for name, content, mode in members:
            member = zipfile.ZipInfo(name)
            member.external_attr = mode << 16
            output.writestr(member, content)
    raw = path.read_bytes()
    # ZipInfo normalizes os.sep on Windows when writing. Fault injection must
    # change the actual local/central header bytes, not merely its constructor.
    for name, _, _ in members:
        if "\\" in name:
            raw = raw.replace(name.replace("\\", "/").encode(), name.encode())
    path.write_bytes(raw)
    return {"path": path.name, "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}


def test_extract_binds_actual_member_bytes_and_is_create_once(tmp_path):
    ref = bundle(tmp_path, [("windows/part.json", b'{"status":"PASS"}', stat.S_IFREG | 0o644),
                            ("linux/run.log", b"complete\n", stat.S_IFREG | 0o600)])
    dest = tmp_path / "retained"
    result = archive.extract(tmp_path, ref, dest)
    assert [item["path"] for item in result] == ["windows/part.json", "linux/run.log"]
    assert (dest / "linux/run.log").read_bytes() == b"complete\n"
    with pytest.raises(QualificationError, match="spent"):
        archive.extract(tmp_path, ref, dest)


@pytest.mark.parametrize("name,mode", [("../escape.json", 0o644), ("C:/escape.json", 0o644),
                                     ("link.json", stat.S_IFLNK | 0o777), ("execute.json", 0o755),
                                     ("payload.py", 0o644), ("a\\b.json", 0o644)])
def test_unsafe_members_rejected_before_destination_is_created(tmp_path, name, mode):
    ref = bundle(tmp_path, [(name, b"unsafe", mode)])
    dest = tmp_path / "retained"
    with pytest.raises(QualificationError):
        archive.extract(tmp_path, ref, dest)
    assert not dest.exists()


@pytest.mark.parametrize("names", [("a.json", "A.json"), ("a.json", "a.json/inside.log")])
def test_member_aliases_and_file_directory_conflicts_rejected(tmp_path, names):
    ref = bundle(tmp_path, [(name, b"data", 0o644) for name in names])
    with pytest.raises(QualificationError):
        archive.extract(tmp_path, ref, tmp_path / "retained")


def test_changed_archive_and_member_budget_are_rejected(tmp_path, monkeypatch):
    ref = bundle(tmp_path, [("part.json", b"12345678", 0o644)])
    with pytest.raises(QualificationError, match="digest"):
        archive.extract(tmp_path, {**ref, "sha256": "0" * 64}, tmp_path / "wrong")
    monkeypatch.setattr(archive, "MAX_MEMBER_BYTES", 4)
    with pytest.raises(QualificationError, match="size"):
        archive.extract(tmp_path, ref, tmp_path / "oversize")
