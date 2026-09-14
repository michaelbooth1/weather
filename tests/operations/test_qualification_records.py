"""Exercise the evidence boundary with malformed and redirected inputs."""

from __future__ import annotations

import hashlib
import os

import pytest

from weather.operations.qualification import records as r


@pytest.mark.parametrize("raw", [
    b'{"status":"PASS","status":"FAIL"}', b'{"nested":{"a":1,"a":2}}',
    b'{"run_id":123.0}', b'{"value":NaN}', b'{"value":Infinity}', b'[]',
    b'\xef\xbb\xbf{}', b'{"x":"\\u0000"}', b'{"n":9223372036854775808}',
    b'{"x":' + b'[' * 40 + b'0' + b']' * 40 + b'}',
])
def test_rejects_ambiguous_records(raw):
    with pytest.raises(r.QualificationError):
        r.decode(raw)


@pytest.mark.parametrize("path", ["../secret", "a/../secret", "C:/secret", "/secret", "a\\b",
                                      "a//b", "a/./b", "a/CON.txt", "a/nul", "a/b.", "a/b ", "a:b"])
def test_downloaded_paths_cannot_escape_or_alias(path):
    with pytest.raises(r.QualificationError):
        r.relative_path(path)


def test_case_fold_collision_is_rejected_on_every_platform():
    with pytest.raises(r.QualificationError):
        r.distinct_paths(["runs/Windows.json", "runs/windows.json"])


def test_receipt_binds_original_bytes_and_is_create_once(tmp_path):
    ref = r.publish(tmp_path, "receipt.json", {"status": "PASS", "run_id": "9007199254740993"})
    assert r.read(tmp_path, ref).value["run_id"] == "9007199254740993"
    with pytest.raises(FileExistsError):
        r.publish(tmp_path, "receipt.json", {"status": "FAIL"})
    assert r.read(tmp_path, ref).value["status"] == "PASS"
    path = tmp_path / ref["path"]
    path.write_bytes(path.read_bytes().replace(b"PASS", b"FAIL"))
    with pytest.raises(r.QualificationError, match="digest"):
        r.read(tmp_path, ref)


def test_partial_record_cannot_be_consumed(tmp_path):
    raw = b'{"status":"PASS"}\n'
    (tmp_path / "partial.json").write_bytes(raw[:-2])
    with pytest.raises(r.QualificationError):
        r.read(tmp_path, {"path": "partial.json", "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})


def test_read_detects_same_length_rewrite_during_open(tmp_path):
    path = tmp_path / "record.json"
    path.write_bytes(b'{"n":1}')
    with pytest.raises(r.QualificationError, match="changed"):
        with r.open_record(tmp_path, path.name) as handle:
            assert handle.read() == b'{"n":1}'
            path.write_bytes(b'{"n":2}')


def test_hard_link_is_not_independent_evidence(tmp_path):
    path = tmp_path / "source.json"
    path.write_bytes(b"{}")
    os.link(path, tmp_path / "alias.json")
    with pytest.raises(r.QualificationError, match="hard-linked"):
        with r.open_record(tmp_path, "alias.json"):
            pytest.fail("alias was exposed to the reader")


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink case; Windows reparse coverage is native fixture work")
def test_parent_symlink_is_rejected_before_read(tmp_path):
    outside = tmp_path / "actual"
    outside.mkdir()
    (outside / "record.json").write_bytes(b"{}")
    (tmp_path / "alias").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        with r.open_record(tmp_path, "alias/record.json"):
            pytest.fail("redirected bytes were exposed")


def test_boolean_is_not_a_byte_count():
    with pytest.raises(r.QualificationError):
        r.reference({"path": "receipt.json", "size": True, "sha256": "a" * 64})
