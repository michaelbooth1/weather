"""Only explicitly sealed content identities allow shared-file hash reuse."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from weather.reporting.source_gates import settlement_source_audit as audit


def _inputs(root):
    payload = root / "shared.json"
    payload.write_bytes(b'{"value":1}')
    ledger = root / "settlements/atlanta/ledger.jsonl"
    ledger.parent.mkdir(parents=True)
    with ledger.open("w", encoding="utf-8") as handle:
        for index in range(20):
            handle.write(json.dumps({
                "event_slug": f"event-{index:03}", "market_id": "atlanta",
                "target_date": "2026-06-19", "quality_grade": "complete",
                "settlement_bucket": 80, "settlement_source": "daily_summary",
                "reconciliation_status": "match", "ledger_path": "",
                "daily_summary_path": str(payload),
            }) + "\n")
    return dict(labels_csv=root / "absent.csv", ledger_root=ledger.parent.parent,
                generated_at_utc="fixed"), payload


def test_only_sealed_inputs_reuse_a_verified_hash(tmp_path, monkeypatch):
    inputs, shared = _inputs(tmp_path)
    digest = hashlib.sha256(shared.read_bytes()).hexdigest()
    calls = []
    original = audit._sha256

    def record(path):
        calls.append(Path(path))
        return original(path)

    monkeypatch.setattr(audit, "_sha256", record)
    with audit.open_settlement_source_audit(**inputs) as payload:
        expected = {**payload, "rows": list(payload["rows"])}
    assert calls == [shared] * 20
    calls.clear()
    with audit.open_settlement_source_audit(**inputs, sealed_lineage_sha256=[(shared, digest)]) as payload:
        assert {**payload, "rows": list(payload["rows"])} == expected
        audit.write_outputs(payload, tmp_path / "audit.json", tmp_path / "audit.md")
    assert calls == [shared] * 3  # first use, completed audit, pre-publication


def test_same_size_same_mtime_mutation_invalidates_seal_and_keeps_output(tmp_path):
    inputs, shared = _inputs(tmp_path)
    digest = hashlib.sha256(shared.read_bytes()).hexdigest()
    stamp = shared.stat()
    output = tmp_path / "audit.json"
    report = tmp_path / "audit.md"
    output.write_bytes(b"previous JSON")
    report.write_bytes(b"previous report")
    with audit.open_settlement_source_audit(**inputs, sealed_lineage_sha256=[(shared, digest)]) as payload:
        shared.write_bytes(b'{"value":2}')
        os.utime(shared, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        with pytest.raises(ValueError, match="Sealed lineage content changed"):
            audit.write_outputs(payload, output, report)
    assert output.read_bytes() == b"previous JSON"
    assert report.read_bytes() == b"previous report"
    assert not list(tmp_path.glob(".settlement-audit-*"))


def test_fresh_invocation_rejects_old_seal_after_late_change(tmp_path):
    inputs, shared = _inputs(tmp_path)
    digest = hashlib.sha256(shared.read_bytes()).hexdigest()
    shared.write_bytes(b'{"value":2}')
    with pytest.raises(ValueError, match="Sealed lineage content changed"):
        with audit.open_settlement_source_audit(**inputs, sealed_lineage_sha256=[(shared, digest)]):
            raise AssertionError("Stale sealed input was accepted")


@pytest.mark.parametrize("entries", [[("relative.json", "0" * 64)], [("ABSOLUTE", "wrong")]])
def test_invalid_seal_fails_closed_and_releases_index(tmp_path, entries):
    inputs, _ = _inputs(tmp_path)
    entries = [(tmp_path / "value" if path == "ABSOLUTE" else path, sha) for path, sha in entries]
    scratch = tmp_path / "work"
    with pytest.raises(ValueError):
        with audit.open_settlement_source_audit(**inputs, scratch_root=scratch,
                                               sealed_lineage_sha256=entries):
            raise AssertionError("Invalid seal was accepted")
    assert list(scratch.iterdir()) == []
