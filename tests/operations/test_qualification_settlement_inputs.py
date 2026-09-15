"""Real audit/resolver parity and complete current dependency discovery."""

from copy import deepcopy
import csv
import json
import os
from pathlib import Path
import sqlite3
import time

import pytest

from weather.operations.qualification.contracts import Graph
from weather.operations.qualification.inputs import ReadBudget, SourceRoots, Stager
from weather.operations.qualification.settlement_inputs import SealedAuditReader, _index_rows, merged_rows, prepare
from weather.reporting.source_gates import settlement_source_audit as audit


@pytest.fixture
def fixture(tmp_path):
    production, attempt = tmp_path / "production", tmp_path / "attempt"
    ledger = production / "data/settlements/market/ledger.jsonl"
    labels = production / "data/labels/market_day_labels.csv"
    payload = production / "data/payloads/summary.json"
    for path in (ledger, labels, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
    attempt.mkdir()
    payload.write_text('{"settlement":21}\n', encoding="utf-8")
    old = {"event_slug": "example", "market_id": "market", "target_date": "2026-09-01", "settlement_bucket": 20,
           "quality_grade": "complete", "reconciliation_status": "mismatch", "daily_summary_path": str(payload)}
    revised = {**old, "settlement_bucket": 21}
    ledger.write_text(json.dumps(old) + "\n" + json.dumps(revised) + "\n", encoding="utf-8")
    with labels.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["event_slug", "market_id", "settlement_bucket", "note"])
        writer.writeheader()
        writer.writerow({"event_slug": "example", "market_id": "market", "settlement_bucket": "", "note": "label overlay"})
    sources = SourceRoots({"production": production}, {"production": ["data/settlements", "data/labels", "data/payloads"]}, relative_root="production")
    stager = Stager(sources, attempt, ReadBudget(64 * 1024**2, time.monotonic() + 30))
    return stager, labels, ledger.parent.parent, payload


def test_sealed_reader_matches_real_audit_and_preserves_truth_blocks(fixture, monkeypatch):
    stager, labels, ledgers, payload = fixture
    expected = audit.build_settlement_source_audit(labels_csv=labels, ledger_root=ledgers, generated_at_utc="fixed fixture time")
    preparation = prepare(stager, labels_identity=str(labels), ledger_root_identity=str(ledgers), markets=["market"])
    assert preparation["counts"] == {"labels": 1, "ledgers": {"market": 2}, "merged_rows": 1}
    ref = stager.seal()
    reader = SealedAuditReader(Graph(stager.root), ref, stager.sources, stager.budget)
    # The algorithm must use the sealed resolver even when every ordinary file
    # reader is unavailable. No fall-through to the mutable production root.
    monkeypatch.setattr(audit, "_read_csv", lambda *args: pytest.fail("unsealed CSV access"))
    monkeypatch.setattr(audit, "_ledger_rows", lambda *args: pytest.fail("unsealed ledger access"))
    monkeypatch.setattr(audit, "_sha256", lambda *args: pytest.fail("unsealed lineage access"))
    actual = audit.build_settlement_source_audit(labels_csv=labels, ledger_root=ledgers, generated_at_utc="fixed fixture time", input_reader=reader)
    assert actual == expected
    assert actual["status"] == "BLOCK" and actual["rows"][0]["promotion_blocker"] is True
    assert actual["rows"][0]["canonical_settlement_bucket"] == 21
    assert actual["rows"][0]["note"] == "label overlay"
    assert reader.verify_staged()


def test_selection_index_preserves_last_encounter_and_nonempty_overlay(tmp_path):
    connection = sqlite3.connect(tmp_path / "index.sqlite")
    connection.execute("CREATE TABLE rows (kind TEXT, slug TEXT, body TEXT, PRIMARY KEY(kind, slug))")
    ledgers = [{"event_slug": "x", "value": 1}, {"event_slug": "x", "value": 2, "kept": "ledger"}, {"event_slug": "z", "value": 9}]
    labels = [{"event_slug": "x", "value": "first", "discarded": "earlier label"}, {"event_slug": "x", "value": "", "added": "label"}, {"event_slug": "y", "value": "label only"}]
    budget = ReadBudget(1024**2, time.monotonic() + 30)
    try:
        _index_rows(connection, "ledger", iter(ledgers), budget=budget)
        _index_rows(connection, "labels", iter(labels), budget=budget)
        assert list(merged_rows(connection)) == audit._merge_label_and_ledger_rows(labels, ledgers)
    finally:
        connection.close()


def test_discovery_does_not_pull_unused_alternative_payloads(fixture):
    stager, labels, ledgers, payload = fixture
    ledger = ledgers / "market/ledger.jsonl"
    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    for row in rows:
        row["weather_com_raw_payload_path"] = str(payload)
        row["weather_com_payload_path"] = "unapproved-unused-alternative"
    ledger.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    prepare(stager, labels_identity=str(labels), ledger_root_identity=str(ledgers), markets=["market"])
    assert len(stager.entries) == 3


@pytest.mark.parametrize("change", ["missing", "extra", "bad_middle"])
def test_preparation_refuses_incomplete_market_coverage_and_malformed_records(fixture, change):
    stager, labels, ledgers, _ = fixture
    if change == "missing":
        (ledgers / "market/ledger.jsonl").unlink()
    elif change == "extra":
        (ledgers / "unexpected").mkdir()
        (ledgers / "unexpected/ledger.jsonl").write_text('{}\n')
    else:
        with (ledgers / "market/ledger.jsonl").open("a") as handle:
            handle.write('bad-record\n')
    with pytest.raises((ValueError, OSError)):
        prepare(stager, labels_identity=str(labels), ledger_root_identity=str(ledgers), markets=["market"])


def test_audit_cannot_resolve_an_undeclared_lineage_path(fixture):
    stager, labels, ledgers, _ = fixture
    prepare(stager, labels_identity=str(labels), ledger_root_identity=str(ledgers), markets=["market"])
    reader = SealedAuditReader(Graph(stager.root), stager.seal(), stager.sources, stager.budget)
    with pytest.raises(ValueError, match="unsealed dependency"):
        reader.lineage("snapshot_tape", "data/payloads/unsealed.json", "not recorded")


def test_staged_payload_changes_invalidate_the_per_invocation_hash_cache(fixture):
    stager, labels, ledgers, payload = fixture
    prepare(stager, labels_identity=str(labels), ledger_root_identity=str(ledgers), markets=["market"])
    reader = SealedAuditReader(Graph(stager.root), stager.seal(), stager.sources, stager.budget)
    reader.lineage("wu_daily_summary", str(payload), "not recorded")
    entry = next(item for item in stager.entries if item["kind"] == "payload")
    copy = stager.root / entry["staged"]["path"]
    copy.chmod(0o600)
    copy.write_bytes(b"altered copy")
    with pytest.raises(ValueError):
        reader.verify_staged()


def test_new_market_ledger_after_sealing_invalidates_current_generation(fixture):
    stager, labels, ledgers, _ = fixture
    prepare(stager, labels_identity=str(labels), ledger_root_identity=str(ledgers), markets=["market"])
    reader = SealedAuditReader(Graph(stager.root), stager.seal(), stager.sources, stager.budget)
    (ledgers / "new-market").mkdir()
    (ledgers / "new-market/ledger.jsonl").write_text('{}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="extra market"):
        reader.revalidate_current()
    with pytest.raises(ValueError, match="extra market"):
        stager.revalidate()
