"""Frozen settlement semantics, including encounter order and label replacement."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from weather.reporting.source_gates import settlement_source_audit as audit


GENERATED_AT = "2026-09-12T00:00:00+00:00"
GOLDEN = Path(__file__).parents[1] / "fixtures/settlement_source_audit/legacy_v01.json"


def make_corpus(root: Path) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    daily = root / "daily summary.csv"
    daily.write_text("date,high\n2026-06-19,80\n", encoding="utf-8")
    tape = root / "snapshot tape.csv"
    tape.write_text("id,high\na,80\n", encoding="utf-8")
    base = {
        "market_id": "atlanta", "target_date": "2026-06-19",
        "settlement_bucket": "80", "settlement_source": "daily_summary",
        "quality_grade": "complete", "reconciliation_status": "match",
        "resolution_timezone": "America/New_York",
        "finalized_at_utc": "2026-06-20T06:00:00+00:00",
        "daily_summary_path": str(daily), "snapshot_tape_path": str(tape),
    }

    def row(slug, **values):
        return {**base, "event_slug": slug, **values}

    first = [
        row("duplicate", settlement_bucket="82", finalized_at_utc="2026-06-25T00:00:00Z"),
        row("duplicate", settlement_bucket="83", finalized_at_utc="2026-06-26T00:00:00Z"),
        row("cross-file", settlement_bucket="90", finalized_at_utc="2026-06-27T00:00:00Z"),
        row("provisional", quality_grade="partial", reconciliation_status="pending"),
        row("partial-countable", quality_grade="partial", promotion_countable=True,
            note="snapshot high=79 disagrees with daily_summary=80"),
        row("partial-excluded", quality_grade="partial", promotion_countable=False),
        row("manual", quality_grade="manual_override", settlement_source="override"),
        row("stale", quality_grade="stale_source"),
        row("mismatch", reconciliation_status="mismatch", polymarket_winning_band="81°F"),
        row("revision", note="daily_summary=79 disagrees with snapshot high=80"),
        row("unavailable", reconciliation_status="unavailable"),
        row("missing-bucket", settlement_bucket=""),
        row("missing-paths", daily_summary_path=str(root / "absent.csv"),
            snapshot_tape_path="", ledger_path=""),
        row("celsius", market_id="toronto", target_date="2026-06-20",
            settlement_bucket="20", wu_final_bucket="20", polymarket_winning_band="20°C",
            resolution_timezone="America/Toronto", finalized_at_utc="2026-06-21T06:00:00Z"),
        row("unicode-東京", market_id="", resolution_timezone="Invalid/Zone",
            note='braces { } and "quotes", café, 東京\nsecond line'),
        row("unknown-market", market_id=None, snapshot_high_bucket="79"),
        row("explicit-unknown", market_id="unknown", snapshot_high_bucket="79"),
        row("empty-date", target_date="", finalized_at_utc="invalid"),
        row("", settlement_bucket="99"),
    ]
    last = [
        row("cross-file", settlement_bucket="75", finalized_at_utc="2026-06-20T06:00:00Z"),
        row("duplicate", settlement_bucket="79", note="ledger note survives empty label",
            finalized_at_utc="2026-06-20T06:00:00Z"),
    ]
    ledgers = root / "settlements"
    for market, rows in (("a-first", first), ("z-last", last)):
        path = ledgers / market / "ledger.jsonl"
        path.parent.mkdir(parents=True)
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            for value in rows:
                handle.write(json.dumps(value, ensure_ascii=False) + "\n")
            handle.write("\n{invalid json\n")
    labels = root / "labels.csv"
    label_rows = [
        {"event_slug": "duplicate", "settlement_bucket": "86", "quality_grade": "manual_override",
         "note": "old label must not survive whole-row replacement"},
        {"event_slug": "duplicate", "settlement_bucket": "80", "quality_grade": "", "note": ""},
        row("label-only", ledger_path="", target_date="2026-06-21"),
        {"event_slug": "", "settlement_bucket": "100"},
    ]
    with labels.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=sorted({key for value in label_rows for key in value}))
        writer.writeheader()
        writer.writerows(label_rows)
    return labels, ledgers


def normalized(value, root: Path):
    if isinstance(value, dict):
        result = {key: normalized(item, root) for key, item in value.items()}
        if result.get("sha256") and "source" in result and "path" in result:
            # File hashes remain checked independently. Ledger bytes include the
            # platform's temporary paths, which are deliberately not golden data.
            result["sha256"] = "<HASH:" + result["source"] + ":" + result["path"] + ">"
        return result
    if isinstance(value, list):
        return [normalized(item, root) for item in value]
    if isinstance(value, str):
        return value.replace(str(root), "<ROOT>").replace("\\", "/")
    return value


def test_audit_matches_frozen_legacy_semantics(tmp_path: Path):
    root = tmp_path / "corpus"
    labels, ledgers = make_corpus(root)
    payload = audit.build_settlement_source_audit(
        labels_csv=labels, ledger_root=ledgers, generated_at_utc=GENERATED_AT,
    )
    by_slug = {row["event_slug"]: row for row in payload["rows"]}
    assert by_slug["duplicate"]["canonical_settlement_bucket"] == 80
    assert by_slug["duplicate"]["quality_grade"] == "complete"
    assert by_slug["duplicate"]["note"] == "ledger note survives empty label"
    assert by_slug["cross-file"]["canonical_settlement_bucket"] == 75
    assert by_slug["partial-countable"]["proof_grade_label"] is True
    assert by_slug["partial-excluded"]["proof_grade_label"] is False
    for row in payload["rows"]:
        for entry in row["lineage"]:
            if entry["sha256"]:
                assert entry["sha256"] == hashlib.sha256(Path(entry["path"]).read_bytes()).hexdigest()
    record = normalized({
        "payload": payload,
        "markdown": audit.render_report(payload),
        "gates": [audit.settlement_label_gate_for_target_dates(payload, dates) for dates in (
            [], ["2026-06-19"], ["2026-06-20"], ["2026-06-21"], ["2026-06-22"],
            ["2026-06-19", "2026-06-20", "2026-06-21", "2026-06-22"],
        )],
    }, root)
    output = tmp_path / "legacy-result.json"
    output.write_text(json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    assert record == json.loads(GOLDEN.read_text(encoding="utf-8"))
    print("AUDIT_BASELINE", json.dumps({
        "source": str(Path(audit.__file__).resolve()),
        "source_sha256": hashlib.sha256(Path(audit.__file__).read_bytes()).hexdigest(),
        "result": str(output), "result_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "labels": len(payload["rows"]),
    }))
