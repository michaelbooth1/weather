"""Adversarial contracts for exclusive same-directory artifact publication."""

from __future__ import annotations

import csv
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from weather import io as weather_io


WRITER_KINDS = (
    "json",
    "streaming_json",
    "text",
    "csv",
    "bytes",
    "copy",
)


def _publish(kind: str, path: Path, marker: str) -> None:
    if kind == "json":
        weather_io.write_json_atomic(path, {"marker": marker}, trailing_newline=True)
    elif kind == "streaming_json":
        weather_io.write_json_streaming_atomic(
            path,
            {"marker": marker},
            trailing_newline=True,
        )
    elif kind == "text":
        weather_io.write_text_atomic(path, f"text:{marker}\n")
    elif kind == "csv":
        weather_io.write_csv_rows_atomic(
            path,
            ("marker",),
            ({"marker": marker},),
        )
    elif kind == "bytes":
        weather_io.write_bytes_atomic(path, f"bytes:{marker}".encode("utf-8"))
    elif kind == "copy":
        source = path.parent / f"copy-source-{marker[:13]}.bin"
        source.write_bytes(f"copy:{marker}".encode("utf-8"))
        weather_io.copy_file_atomic(source, path)
    else:  # pragma: no cover - the parametrization is the contract
        raise AssertionError(kind)


def _read_marker(kind: str, path: Path) -> str:
    if kind in {"json", "streaming_json"}:
        return str(json.loads(path.read_text(encoding="utf-8"))["marker"])
    if kind == "text":
        return path.read_text(encoding="utf-8").strip().removeprefix("text:")
    if kind == "csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            return str(next(csv.DictReader(handle))["marker"])
    prefix = b"bytes:" if kind == "bytes" else b"copy:"
    content = path.read_bytes()
    assert content.startswith(prefix)
    return content[len(prefix) :].decode("utf-8")


def _hardlink(source: Path, link: Path) -> None:
    try:
        os.link(source, link)
    except OSError as exc:
        pytest.skip(f"hard links unavailable: {exc}")


@pytest.mark.parametrize("kind", WRITER_KINDS)
def test_atomic_writer_severs_existing_destination_hardlink(kind, tmp_path):
    protected = tmp_path / "protected.bin"
    protected.write_bytes(b"sealed evidence")
    destination = tmp_path / f"result-{kind}.artifact"
    _hardlink(protected, destination)

    _publish(kind, destination, "winner")

    assert protected.read_bytes() == b"sealed evidence"
    assert _read_marker(kind, destination) == "winner"
    assert not destination.samefile(protected)


@pytest.mark.parametrize("kind", WRITER_KINDS)
def test_atomic_writer_ignores_precreated_predictable_temp_hardlinks(kind, tmp_path):
    protected = tmp_path / "protected.bin"
    protected.write_bytes(b"sealed evidence")
    destination = tmp_path / f"result-{kind}.artifact"
    predictable = (
        destination.with_name(destination.name + ".tmp"),
        destination.with_name(destination.name + f".tmp-{os.getpid()}"),
        destination.with_name(destination.name + f".{os.getpid()}.123.tmp"),
    )
    for temp in predictable:
        _hardlink(protected, temp)

    _publish(kind, destination, "winner")

    assert protected.read_bytes() == b"sealed evidence"
    assert _read_marker(kind, destination) == "winner"
    for temp in predictable:
        assert temp.samefile(protected)
        assert temp.read_bytes() == b"sealed evidence"


@pytest.mark.parametrize("kind", WRITER_KINDS)
def test_concurrent_atomic_writers_publish_one_complete_candidate(kind, tmp_path):
    destination = tmp_path / f"concurrent-{kind}.artifact"
    candidate_count = 12
    barrier = threading.Barrier(candidate_count)

    def publish(index: int) -> None:
        marker = f"candidate-{index:02d}-" + (str(index) * 4096)
        barrier.wait(timeout=10)
        _publish(kind, destination, marker)

    with ThreadPoolExecutor(max_workers=candidate_count) as executor:
        list(executor.map(publish, range(candidate_count)))

    marker = _read_marker(kind, destination)
    assert marker in {
        f"candidate-{index:02d}-" + (str(index) * 4096)
        for index in range(candidate_count)
    }
    assert not list(tmp_path.glob(f".{destination.name}.*.tmp"))


def test_failed_replace_preserves_destination_and_removes_temp(tmp_path, monkeypatch):
    destination = tmp_path / "result.json"
    destination.write_text('{"marker": "sealed"}\n', encoding="utf-8")

    def deny_replace(_self, _target):
        raise PermissionError("destination remains locked")

    monkeypatch.setattr(Path, "replace", deny_replace)
    with pytest.raises(PermissionError, match="remains locked"):
        weather_io.write_json_atomic(
            destination,
            {"marker": "candidate"},
            retries=2,
            sleep_fn=lambda _seconds: None,
        )

    assert json.loads(destination.read_text(encoding="utf-8")) == {"marker": "sealed"}
    assert not list(tmp_path.glob(f".{destination.name}.*.tmp"))


def test_failed_stream_preserves_destination_and_removes_temp(tmp_path):
    destination = tmp_path / "result.csv"
    destination.write_bytes(b"marker\r\nsealed\r\n")

    def broken_rows():
        yield {"marker": "partial"}
        raise RuntimeError("stream failed")

    with pytest.raises(RuntimeError, match="stream failed"):
        weather_io.write_csv_rows_atomic(
            destination,
            ("marker",),
            broken_rows(),
        )

    assert destination.read_text(encoding="utf-8").splitlines() == ["marker", "sealed"]
    assert not list(tmp_path.glob(f".{destination.name}.*.tmp"))


@pytest.mark.skipif(os.name != "nt", reason="Windows extended-path regression")
def test_atomic_writer_supports_long_sibling_temp_path(tmp_path):
    parent = tmp_path
    while len(str(parent)) < 225:
        remaining = 225 - len(str(parent)) - 1
        parent /= "x" * max(1, min(remaining, 20))
    parent.mkdir(parents=True)
    destination = parent / "experiment_result.json"
    representative_temp = parent / (
        f".{destination.name}." + ("x" * 8) + ".tmp"
    )
    assert len(str(destination)) < 260
    assert len(str(representative_temp)) >= 260

    weather_io.write_json_atomic(
        destination,
        {"status": "COMPLETE"},
        trailing_newline=True,
    )

    assert json.loads(destination.read_text(encoding="utf-8")) == {
        "status": "COMPLETE"
    }
    assert not list(parent.glob(f".{destination.name}.*.tmp"))
