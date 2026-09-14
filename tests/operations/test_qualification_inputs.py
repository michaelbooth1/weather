"""Full source generations and strict input integrity, using disposable fixtures."""

import hashlib
import os
from pathlib import Path
import time

import pytest

from weather.operations.qualification import inputs
from weather.operations.qualification.contracts import Graph


def budget(maximum=64 * 1024**2):
    return inputs.ReadBudget(maximum, time.monotonic() + 30)


@pytest.fixture
def staging(tmp_path):
    production, output = tmp_path / "production", tmp_path / "attempt"
    (production / "data/settlements/market").mkdir(parents=True)
    output.mkdir()
    roots = inputs.SourceRoots({"production": production}, {"production": ["data/settlements"]}, relative_root="production")
    return inputs.Stager(roots, output, budget()), production / "data/settlements/market/ledger.jsonl"


def test_staging_preserves_bytes_and_charges_every_source_read(staging):
    stager, source = staging
    raw = b'{"event_slug":"example","temperature":21.5}\n\n'
    source.write_bytes(raw)
    entry = stager.stage(str(source), mandatory=True, kind="ledger")
    assert (stager.root / entry["staged"]["path"]).read_bytes() == raw
    assert stager.budget.observed_bytes == 2 * len(raw)
    assert list(inputs.ledger_rows(stager.root, entry["staged"], stager.budget)) == [{"event_slug": "example", "temperature": 21.5}]
    assert stager.budget.observed_bytes == 3 * len(raw)
    ref = stager.seal()
    graph = Graph(stager.root)
    manifest = graph.get(ref)
    assert manifest["file_count"] == 1 and manifest["staged_bytes"] == len(raw)
    assert manifest["validation"]["read_bytes"] == 4 * len(raw)
    assert graph.get(manifest["pages"][0])["entries"][0]["identities"] == [str(source)]


@pytest.mark.parametrize("mutation", ["append", "replace", "rewrite"])
def test_complete_generation_drift_cannot_reuse_a_staged_input(staging, mutation):
    stager, source = staging
    source.write_bytes(b'{"value":"a"}\n')
    initial = source.stat()
    stager.stage(str(source), mandatory=True, kind="ledger")
    if mutation == "append":
        with source.open("ab") as handle:
            handle.write(b'{"value":"b"}\n')
    elif mutation == "replace":
        alternate = source.with_name("replacement")
        alternate.write_bytes(source.read_bytes())
        os.replace(alternate, source)
    else:
        source.write_bytes(b'{"value":"b"}\n')
        os.utime(source, ns=(initial.st_atime_ns, initial.st_mtime_ns))
    with pytest.raises(ValueError, match="drift"):
        stager.revalidate()


def test_mutation_during_copy_is_not_sealed(staging, monkeypatch):
    stager, source = staging
    source.write_bytes(b'{"value":"a"}\n')
    original = inputs._hash_handle
    calls = []

    def mutate(handle, size, budget, output=None):
        result = original(handle, size, budget, output)
        calls.append(result)
        if output is not None:
            source.write_bytes(b'{"value":"b"}\n')
        return result

    monkeypatch.setattr(inputs, "_hash_handle", mutate)
    with pytest.raises(ValueError, match="changed"):
        stager.stage(str(source), mandatory=True)
    assert len(calls) == 2
    assert not (stager.root / "inputs.json").exists()


def test_optional_absence_is_preserved_and_appearance_invalidates(staging):
    stager, source = staging
    entry = stager.stage(str(source))
    assert entry["present"] is False and entry["missing_reason"] == "path_not_found"
    stager.revalidate()
    source.write_bytes(b"now present")
    with pytest.raises(ValueError, match="appeared"):
        stager.revalidate()


def test_missing_mandatory_input_cannot_be_an_optional_lineage_gap(staging):
    stager, source = staging
    with pytest.raises((ValueError, OSError)):
        stager.stage(str(source), mandatory=True, kind="ledger")


@pytest.mark.parametrize("identity", ["../escape", "data/settlements/../private", "data/credentials/key", "https://example/file", "C:relative"])
def test_source_row_cannot_expand_approved_root(staging, identity):
    stager, _ = staging
    with pytest.raises(ValueError):
        stager.stage(identity)


def test_repeated_canonical_source_is_copied_once(staging):
    stager, source = staging
    source.write_bytes(b"retained bytes")
    first = stager.stage(str(source))
    second = stager.stage("data/settlements/market/ledger.jsonl")
    assert first is second and len(stager.entries) == 1
    assert len(first["identities"]) == 2 and stager.budget.observed_bytes == 2 * source.stat().st_size


def test_stage_refuses_file_count_and_total_byte_budget(staging):
    stager, source = staging
    source.write_bytes(b"12345")
    stager.maximum_bytes = 4
    with pytest.raises(ValueError, match="reservation"):
        stager.stage(str(source))
    assert list((stager.root / "files").iterdir()) == []


def test_staging_namespace_is_create_once(staging):
    stager, _ = staging
    with pytest.raises(FileExistsError):
        inputs.Stager(stager.sources, stager.root, budget())


def staged_blob(tmp_path, raw):
    (tmp_path / "input.bin").write_bytes(raw)
    return {"path": "input.bin", "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}


@pytest.mark.parametrize("raw", [b'{"ok":1}\nnot-json\n', b'{"ok":1}', b'[]\n', b'{"x":1,"x":2}\n', b'{"x":NaN}\n', b'{"x":1e999}\n'])
def test_strict_ledger_rejects_malformed_middle_tail_types_and_numbers(tmp_path, raw):
    ref = staged_blob(tmp_path, raw)
    with pytest.raises((ValueError, UnicodeError)):
        list(inputs.ledger_rows(tmp_path, ref, budget()))


@pytest.mark.parametrize("raw", [b"a,a\n1,2\n", b"a,b\n1,2,3\n", b"a,b\n1\n", b'a,b\n"unfinished,2\n'])
def test_labels_reject_duplicate_headers_bad_width_and_incomplete_record(tmp_path, raw):
    ref = staged_blob(tmp_path, raw)
    with pytest.raises((ValueError, inputs.csv.Error)):
        list(inputs.label_rows(tmp_path, ref, budget()))


def test_labels_preserve_quoted_newlines_and_charge_actual_input_bytes(tmp_path):
    raw = b'a,b\r\n"line 1\nline 2",value\r\n'
    ref, readings = staged_blob(tmp_path, raw), budget()
    assert list(inputs.label_rows(tmp_path, ref, readings)) == [{"a": "line 1\nline 2", "b": "value"}]
    assert readings.observed_bytes == len(raw)


def test_parser_cannot_trust_tampered_staged_bytes(tmp_path):
    ref = staged_blob(tmp_path, b'{"value":"a"}\n')
    (tmp_path / "input.bin").write_bytes(b'{"value":"b"}\n')
    with pytest.raises(ValueError, match="bytes differ"):
        list(inputs.ledger_rows(tmp_path, ref, budget()))


def test_read_budget_expires_without_an_implicit_partial_success(tmp_path):
    ref = staged_blob(tmp_path, b'{"ok":1}\n')
    with pytest.raises(ValueError, match="byte budget"):
        list(inputs.ledger_rows(tmp_path, ref, budget(1)))
    expired = inputs.ReadBudget(1024, time.monotonic() - 1)
    with pytest.raises(ValueError, match="deadline"):
        list(inputs.ledger_rows(tmp_path, ref, expired))


def test_current_read_rejects_hard_link_alias(staging):
    stager, source = staging
    source.write_bytes(b"fixture")
    os.link(source, source.with_name("alias"))
    with pytest.raises(ValueError, match="hard-linked"):
        stager.stage(str(source))
