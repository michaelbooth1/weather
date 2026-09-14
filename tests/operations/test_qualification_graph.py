"""Retained binary evidence stays bound across later verification boundaries."""

import hashlib

import pytest

from weather.operations.qualification.contracts import Graph
from weather.operations.qualification.records import QualificationError


def test_blob_is_counted_once_and_rehashed_at_fresh_boundary(tmp_path):
    (tmp_path / "run.log").write_bytes(b"first")
    ref = {"path": "run.log", "size": 5, "sha256": hashlib.sha256(b"first").hexdigest()}
    graph = Graph(tmp_path, maximum_bytes=1, maximum_blob_bytes=5)
    graph.blob(ref)
    graph.blob(ref)
    assert graph.blob_bytes == 5 and graph.total_bytes == 0
    graph.fresh()
    (tmp_path / "run.log").write_bytes(b"other")
    with pytest.raises(QualificationError, match="bytes differ"):
        graph.fresh()


def test_blob_alias_and_total_size_limit_fail_closed(tmp_path):
    (tmp_path / "run.log").write_bytes(b"first")
    (tmp_path / "next.log").write_bytes(b"next")
    ref = {"path": "run.log", "size": 5, "sha256": hashlib.sha256(b"first").hexdigest()}
    graph = Graph(tmp_path, maximum_blob_bytes=5)
    graph.blob(ref)
    with pytest.raises(QualificationError, match="alias"):
        graph.blob({**ref, "path": "RUN.log"})
    with pytest.raises(QualificationError, match="artifact limit"):
        graph.blob({"path": "next.log", "size": 4, "sha256": hashlib.sha256(b"next").hexdigest()})
