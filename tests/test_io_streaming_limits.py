"""Encoded byte limits retain the previous valid JSON on interrupted output."""

import json
import os

import pytest

from weather.io import write_json_streaming_atomic


@pytest.mark.parametrize("newline", ["\n", "\r\n", None])
def test_streaming_limit_counts_actual_encoded_bytes_and_keeps_old_file(tmp_path, newline):
    path = tmp_path / "output.json"
    payload = {"rows": [{"name": "東京 café"}, {"count": 2}]}
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    physical = text.replace("\n", os.linesep if newline is None else newline)
    size = len(physical.encode("utf-8"))
    write_json_streaming_atomic(path, payload, trailing_newline=True, newline=newline, max_bytes=size)
    assert path.read_bytes() == physical.encode("utf-8")
    with pytest.raises(ValueError, match="max_bytes"):
        write_json_streaming_atomic(path, payload, trailing_newline=True, newline=newline, max_bytes=size - 1)
    assert path.read_bytes() == physical.encode("utf-8")
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_invalid_limits_fail_before_output_creation(tmp_path, limit):
    with pytest.raises(ValueError, match="positive integer"):
        write_json_streaming_atomic(tmp_path / "audit.json", {}, max_bytes=limit)
    assert list(tmp_path.iterdir()) == []
