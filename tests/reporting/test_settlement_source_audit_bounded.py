"""Indexed audit lifecycle, legacy-file readers, and publication failure cases."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import sqlite3
import tracemalloc

import pytest

from weather.reporting.source_gates import settlement_source_audit as audit
from weather.reporting.source_gates import settlement_audit_store as storage
from weather.reporting.source_gates.settlement_audit_reader import AuditJsonRows


def _corpus(root, rows=None):
    ledger_root = root / "settlements"
    path = ledger_root / "atlanta/ledger.jsonl"
    path.parent.mkdir(parents=True)
    if rows is None:
        rows = [{"event_slug": "a", "market_id": "atlanta", "target_date": "2026-06-19",
                 "settlement_bucket": 80, "settlement_source": "daily_summary",
                 "quality_grade": "complete", "reconciliation_status": "match"}]
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    return root / "absent-labels.csv", ledger_root, path


def test_indexed_rows_repeat_within_context_and_close_without_leaks(tmp_path):
    labels, ledgers, _ = _corpus(tmp_path)
    scratch = tmp_path / "work"
    with audit.open_settlement_source_audit(labels_csv=labels, ledger_root=ledgers,
                                           scratch_root=scratch) as payload:
        rows = payload["rows"]
        assert list(rows) == list(rows)
        assert len(rows) == 1
        assert list(rows.iter_target_dates(["missing"])) == []
        assert audit.settlement_label_gate_for_target_dates(payload, ["missing"])["blockers"] == [
            "missing:missing_audit_row"]
        assert list(scratch.iterdir())
    assert list(scratch.iterdir()) == []
    with pytest.raises(RuntimeError, match="outside"):
        list(rows)


def test_next_invocation_reconsiders_appended_ledger_revision(tmp_path):
    labels, ledgers, ledger = _corpus(tmp_path)
    with audit.open_settlement_source_audit(labels_csv=labels, ledger_root=ledgers) as payload:
        original = list(payload["rows"])[0]
    value = json.loads(ledger.read_text().splitlines()[0])
    value["settlement_bucket"] = 81
    value["finalized_at_utc"] = "2000-01-01T00:00:00Z"
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value) + "\n")
    with audit.open_settlement_source_audit(labels_csv=labels, ledger_root=ledgers) as payload:
        changed = list(payload["rows"])[0]
    assert original["canonical_settlement_bucket"] == 80
    assert changed["canonical_settlement_bucket"] == 81
    assert original["lineage"] != changed["lineage"]


@pytest.mark.parametrize("indent", [None, 2])
@pytest.mark.parametrize("chunk", [1, 3, 19, 65536])
def test_reader_handles_legacy_layouts_unicode_and_number_chunk_edges(tmp_path, indent, chunk):
    rows = [{"target_date": "2026-06-19", "market_id": "東京", "promotion_blocker": False,
             "note": 'quotes " } ] café\nline', "number": 1.235e-30},
            {"target_date": "2026-06-18", "promotion_blocker": True, "status": "PROVISIONAL"}]
    value = {"summary": {"nested": {"rows": [42]}}, "rows": rows, "status": "BLOCK"}
    path = tmp_path / "audit.json"
    path.write_text(json.dumps(value, ensure_ascii=False, indent=indent), encoding="utf-8")
    stream = AuditJsonRows(path, chunk_chars=chunk)
    assert list(stream) == rows
    assert stream.metadata["status"] == "BLOCK"
    assert stream.has_fields
    gate = audit.settlement_label_gate_from_path(path, ["2026-06-19"])
    assert gate["status"] == "PASS"
    assert gate["audit_status"] == "BLOCK"


@pytest.mark.parametrize("suffix", ["", " garbage", ",", "]"])
def test_incomplete_or_invalid_tail_never_passes_from_earlier_good_rows(tmp_path, suffix):
    path = tmp_path / "audit.json"
    path.write_text('{"rows":[{"target_date":"2026-06-19","promotion_blocker":false}]' + suffix)
    gate = audit.settlement_label_gate_from_path(path, ["2026-06-19"])
    assert gate["status"] == "BLOCK"
    assert gate["blockers"] == ["settlement_source_audit_missing"]
    assert gate["audit_status"] == "MISSING"


@pytest.mark.parametrize("text", [
    '{"rows":[],"rows":[{"target_date":"2026-06-19","promotion_blocker":false}]}',
    '{"rows":[42]}', '{"rows":{}}', '{"rows":[],}', '{"status":{"rows":[]}}',
])
def test_ambiguous_or_malformed_audit_files_fail_closed(tmp_path, text):
    path = tmp_path / "audit.json"
    path.write_text(text)
    assert audit.settlement_label_gate_from_path(path, ["2026-06-19"])["status"] == "BLOCK"


@pytest.mark.parametrize("value", [{}, {"rows": []}, {"rows": None}, {"rows": [], "status": "BLOCK"}])
def test_empty_audits_keep_the_legacy_missing_evidence_gate(tmp_path, value):
    path = tmp_path / "audit.json"
    path.write_text(json.dumps(value))
    gate = audit.settlement_label_gate_from_path(path, ["2026-06-19"])
    assert gate["blockers"] == ["settlement_source_audit_missing"]
    assert gate["audit_status"] == (value.get("status") if value else "MISSING")


def test_file_gate_does_not_materialize_unrelated_history(tmp_path, monkeypatch):
    path = tmp_path / "audit.json"
    with path.open("w", encoding="utf-8") as handle:
        handle.write('{"rows":[')
        for ordinal in range(10000):
            handle.write(json.dumps({"target_date": "2000-01-01", "note": "p" * 1024,
                                     "promotion_blocker": True}) + ",")
        handle.write('{"target_date":"2026-06-19","promotion_blocker":false}],"status":"BLOCK"}')
    original = Path.read_text

    def no_whole_audit_read(self, *args, **kwargs):
        if self == path:
            raise AssertionError("Whole audit read would restore unbounded memory growth")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", no_whole_audit_read)
    tracemalloc.start()
    try:
        gate = audit.settlement_label_gate_from_path(path, ["2026-06-19"])
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert gate["status"] == "PASS"
    assert peak < 2 * 1024 * 1024


def test_reader_rejects_one_oversized_value_before_unbounded_growth(tmp_path):
    path = tmp_path / "audit.json"
    path.write_text(json.dumps({"rows": [{"note": "x" * 1000}]}))
    with pytest.raises(storage.AuditResourceLimit):
        list(AuditJsonRows(path, max_value_chars=128, chunk_chars=31))


def test_complete_streamed_output_matches_legacy_json_and_gate(tmp_path):
    labels, ledgers, _ = _corpus(tmp_path)
    expected = audit.build_settlement_source_audit(labels_csv=labels, ledger_root=ledgers,
                                                  generated_at_utc="fixed")
    with audit.open_settlement_source_audit(labels_csv=labels, ledger_root=ledgers,
                                           generated_at_utc="fixed") as payload:
        out, report = audit.write_outputs(payload, tmp_path / "audit.json", tmp_path / "audit.md")
    assert json.loads(out.read_text()) == expected
    assert out.read_text() == json.dumps(expected, indent=2, sort_keys=True, default=str) + "\n"
    assert report.read_text() == audit.render_report(expected)
    gate = audit.settlement_label_gate_from_path(out, ["2026-06-19"])
    assert {key: value for key, value in gate.items() if key not in {"path", "audit_status"}} == (
        audit.settlement_label_gate_for_target_dates(expected, ["2026-06-19"]))


def test_output_limit_preserves_both_previous_reports_and_cleans_staging(tmp_path):
    labels, ledgers, _ = _corpus(tmp_path)
    output = tmp_path / "audit.json"
    report = tmp_path / "audit.md"
    output.write_bytes(b"previous complete JSON")
    report.write_bytes(b"previous complete report")
    with audit.open_settlement_source_audit(labels_csv=labels, ledger_root=ledgers) as payload:
        with pytest.raises(ValueError, match="max_bytes"):
            audit.write_outputs(payload, output, report, max_output_bytes=128)
    assert output.read_bytes() == b"previous complete JSON"
    assert report.read_bytes() == b"previous complete report"
    assert not list(tmp_path.glob(".settlement-audit-*"))


def test_cancelled_audit_keeps_previous_outputs_and_releases_index(tmp_path):
    labels, ledgers, _ = _corpus(tmp_path)
    scratch = tmp_path / "work"
    stop = False
    output = tmp_path / "audit.json"
    report = tmp_path / "audit.md"
    output.write_bytes(b"previous JSON")
    report.write_bytes(b"previous report")
    with audit.open_settlement_source_audit(labels_csv=labels, ledger_root=ledgers,
                                           scratch_root=scratch, cancelled=lambda: stop) as payload:
        stop = True
        with pytest.raises(InterruptedError):
            audit.write_outputs(payload, output, report)
    assert output.read_bytes() == b"previous JSON"
    assert report.read_bytes() == b"previous report"
    assert list(scratch.iterdir()) == []


def test_index_disk_limit_fails_before_replacing_any_report(tmp_path):
    rows = ({"event_slug": f"event-{ordinal}", "note": "p" * 4096} for ordinal in range(700))
    labels, ledgers, _ = _corpus(tmp_path, rows)
    scratch = tmp_path / "work"
    output = tmp_path / "audit.json"
    output.write_bytes(b"previous JSON")
    with pytest.raises(sqlite3.DatabaseError, match="full"):
        with audit.open_settlement_source_audit(labels_csv=labels, ledger_root=ledgers,
                                               scratch_root=scratch, max_index_bytes=1024 * 1024):
            raise AssertionError("The oversize index must not be published")
    assert output.read_bytes() == b"previous JSON"
    assert list(scratch.iterdir()) == []


def test_oversized_jsonl_record_fails_closed(tmp_path, monkeypatch):
    labels, ledgers, _ = _corpus(tmp_path, [{"event_slug": "a", "note": "p" * 1024}])
    monkeypatch.setattr(storage, "MAX_RECORD_BYTES", 512)
    with pytest.raises(storage.AuditResourceLimit, match="JSONL record"):
        with audit.open_settlement_source_audit(labels_csv=labels, ledger_root=ledgers):
            raise AssertionError("Oversized input was accepted")


def test_cli_uses_the_context_bound_builder(tmp_path, monkeypatch):
    labels, ledgers, _ = _corpus(tmp_path)

    def materialization_forbidden(**_):
        raise AssertionError("CLI must not use the materialized compatibility API")

    monkeypatch.setattr(audit, "build_settlement_source_audit", materialization_forbidden)
    output = tmp_path / "audit.json"
    assert audit.main(["--labels-csv", str(labels), "--ledger-root", str(ledgers),
                       "--json-out", str(output), "--report-out", str(tmp_path / "audit.md"),
                       "--scratch-root", str(tmp_path / "work")]) == 0
    assert json.loads(output.read_text())["status"] == "PASS"
