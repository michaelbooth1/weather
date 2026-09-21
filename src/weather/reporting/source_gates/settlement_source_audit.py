"""Settlement-source revision and truth-label audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from contextlib import contextmanager, ExitStack
from datetime import datetime, time, timezone
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from weather.backtesting.settlement_ledger import (
    DEFAULT_LABELS_CSV,
    DEFAULT_LEDGER_ROOT,
    parse_band_label,
)
from weather.io import write_json_streaming_atomic, write_text_atomic
from weather.paths import data_path
from weather.reporting.source_gates.settlement_audit_hashes import SealedLineageHashes
from weather.reporting.source_gates.settlement_audit_reader import AuditJsonRows
from weather.reporting.source_gates.settlement_audit_store import AuditStore, DEFAULT_MAX_INDEX_BYTES
from weather.reporting.formatting import markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("settlement_source_revision_audit")
DEFAULT_JSON_OUT = data_path("backtest", "settlement_source_revision_audit.json")
DEFAULT_REPORT_OUT = data_path("backtest", "settlement_source_revision_audit.md")
DEFAULT_MAX_OUTPUT_BYTES = 512 * 1024 * 1024
UNCERTAIN_STATUSES = {
    "PROVISIONAL",
    "SOURCE_STALE",
    "SOURCE_REVISION",
    "SOURCE_DISAGREEMENT",
    "MANUAL_OVERRIDE",
    "UNRECONCILED",
}


def _utc_iso():
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value):
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _maybe_int(value):
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _first_present(row, keys):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _truthy(value):
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "t"}


def _sha256(path):
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _lineage_entry(name, path, missing_reason, sha256):
    if path:
        candidate = Path(path)
        if candidate.exists():
            return {
                "source": name,
                "path": str(candidate),
                "sha256": sha256(candidate),
                "missing_payload_reason": "",
                "status": "HASHED",
            }
        return {
            "source": name,
            "path": str(candidate),
            "sha256": "",
            "missing_payload_reason": "path_not_found",
            "status": "MISSING_WITH_REASON",
        }
    return {
        "source": name,
        "path": "",
        "sha256": "",
        "missing_payload_reason": missing_reason,
        "status": "MISSING_WITH_REASON",
    }


def _lineage(row, sha256):
    entries = [
        _lineage_entry(
            "wu_daily_summary",
            row.get("daily_summary_path"),
            "daily_summary_path_not_recorded",
            sha256,
        ),
        _lineage_entry(
            "snapshot_tape",
            row.get("snapshot_tape_path"),
            "snapshot_tape_path_not_recorded",
            sha256,
        ),
        _lineage_entry(
            "canonical_settlement_ledger",
            row.get("ledger_path"),
            "ledger_path_not_recorded",
            sha256,
        ),
        _lineage_entry(
            "weather_com_max_since_7",
            _first_present(row, ("weather_com_raw_payload_path", "weather_com_payload_path")),
            "weather_com_raw_payload_not_recorded",
            sha256,
        ),
        _lineage_entry(
            "market_resolution",
            _first_present(row, ("market_resolution_payload_path", "gamma_event_payload_path")),
            "market_resolution_raw_payload_not_recorded",
            sha256,
        ),
    ]
    return {
        "status": "PASS" if all(entry.get("sha256") or entry.get("missing_payload_reason") for entry in entries) else "BLOCK",
        "entries": entries,
        "hashed_source_count": sum(1 for entry in entries if entry.get("sha256")),
        "missing_with_reason_count": sum(
            1 for entry in entries
            if not entry.get("sha256") and entry.get("missing_payload_reason")
        ),
    }


def _bucket_from_note(note, pattern):
    match = re.search(pattern, str(note or ""), flags=re.IGNORECASE)
    if not match:
        return None
    return _maybe_int(match.group(1))


def _market_resolution_bucket(row):
    label = row.get("polymarket_winning_band") or row.get("market_resolution_label")
    parsed = parse_band_label(label)
    if parsed.get("kind") == "eq" and parsed.get("value") == parsed.get("value_hi"):
        return parsed.get("value")
    return None


def _source_buckets(row):
    note = row.get("note") or ""
    canonical = _maybe_int(row.get("settlement_bucket"))
    wu_final = _maybe_int(_first_present(row, (
        "wu_final_bucket",
        "wu_daily_summary_bucket",
        "daily_summary_bucket",
    )))
    snapshot = _maybe_int(_first_present(row, (
        "snapshot_high_bucket",
        "settlement_normalized_live_high_bucket",
    )))
    weather_com = _maybe_int(_first_present(row, (
        "weather_com_max_since_7_bucket",
        "weather_com_bucket",
    )))
    live_normalized = _maybe_int(_first_present(row, (
        "settlement_current_high",
        "settlement_normalized_live_high",
    )))
    note_daily = _bucket_from_note(note, r"daily_summary\s*=\s*(-?\d+)")
    note_snapshot = _bucket_from_note(note, r"snapshot high\s*=\s*(-?\d+)")
    if wu_final is None and row.get("settlement_source") == "daily_summary":
        wu_final = canonical
    if wu_final is None:
        wu_final = note_daily
    if snapshot is None:
        snapshot = note_snapshot
    market_resolution = _market_resolution_bucket(row)
    buckets = {
        "canonical_ledger": canonical,
        "wu_final": wu_final,
        "weather_com_max_since_7": weather_com,
        "settlement_normalized_live_high": live_normalized,
        "snapshot_high": snapshot,
        "market_resolution": market_resolution,
    }
    return {key: value for key, value in buckets.items() if value is not None}


def _finalization_lag_hours(row):
    finalized = _parse_time(row.get("finalized_at_utc"))
    target_date = row.get("target_date")
    if not finalized or not target_date:
        return None
    tz_name = row.get("resolution_timezone") or "UTC"
    try:
        zone = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        zone = timezone.utc
    try:
        date_value = datetime.fromisoformat(str(target_date)).date()
    except ValueError:
        return None
    local_close = datetime.combine(date_value, time(23, 59, 59), tzinfo=zone)
    return round((finalized - local_close.astimezone(timezone.utc)).total_seconds() / 3600.0, 6)


def _classify(row, buckets, disagreement_sources):
    quality = str(row.get("quality_grade") or "").strip().lower()
    source = str(row.get("settlement_source") or "").strip().lower()
    reconciliation = str(row.get("reconciliation_status") or "").strip().lower()
    note = str(row.get("note") or "").lower()
    if buckets.get("canonical_ledger") is None:
        return "UNRECONCILED"
    if quality == "manual_override" or source == "override":
        return "MANUAL_OVERRIDE"
    if quality == "stale_source":
        return "SOURCE_STALE"
    if reconciliation == "mismatch":
        return "SOURCE_DISAGREEMENT"
    if disagreement_sources:
        return "SOURCE_REVISION" if "disagrees" in note or "revision" in note else "SOURCE_DISAGREEMENT"
    if quality and quality != "complete":
        return "PROVISIONAL"
    if reconciliation in {"fetch_error", "unavailable", "not_requested"}:
        return "UNRECONCILED"
    return "FINALIZED"


def audit_row(row, *, sha256=None):
    buckets = _source_buckets(row)
    canonical = buckets.get("canonical_ledger")
    disagreement_sources = [
        source for source, bucket in buckets.items()
        if source != "canonical_ledger" and canonical is not None and bucket != canonical
    ]
    lineage = _lineage(row, sha256 or _sha256)
    status = _classify(row, buckets, disagreement_sources)
    alternate_buckets = sorted({
        bucket for source, bucket in buckets.items()
        if source != "canonical_ledger" and canonical is not None and bucket != canonical
    })
    alternate_changes = bool(alternate_buckets)
    # Settlement truth is Polymarket's resolution. A label whose settlement
    # reconciles with Polymarket and whose intraday coverage is *materially*
    # complete is proof-grade for promotion even when the strict zero-gap
    # quality_grade is "partial": partial intraday coverage is a replay-fidelity
    # concern, not a settlement-truth one. item-319 already encodes exactly this
    # in `promotion_countable` (reconciliation_status == "match" AND a countable
    # material_coverage_grade), so consult it rather than re-deriving. When
    # Polymarket itself confirms the bucket, a disagreement from a *secondary* WU
    # source (snapshot/daily_summary) does not change the payout truth and so
    # does not disqualify the label. Strict FINALIZED retains the zero-gap +
    # no-alternate-change bar for any consumer that needs it.
    promotion_countable = _truthy(row.get("promotion_countable"))
    finalized_proof = status == "FINALIZED" and not alternate_changes
    proof_grade = lineage["status"] == "PASS" and (finalized_proof or promotion_countable)
    proof_grade_basis = (
        "finalized" if (proof_grade and finalized_proof)
        else "promotion_countable" if proof_grade
        else None
    )
    return {
        "event_slug": row.get("event_slug"),
        "market_id": row.get("market_id"),
        "target_date": row.get("target_date"),
        "settlement_source": row.get("settlement_source"),
        "quality_grade": row.get("quality_grade"),
        "status": status,
        "promotion_countable": promotion_countable,
        "proof_grade_label": proof_grade,
        "proof_grade_basis": proof_grade_basis,
        "promotion_blocker": not proof_grade,
        "promotion_blocker_reason": "" if proof_grade else (
            row.get("promotion_countable_reason") or status.lower()
            if not promotion_countable else status.lower()
        ),
        "finalization_lag_hours": _finalization_lag_hours(row),
        "reconciliation_status": row.get("reconciliation_status"),
        "canonical_settlement_bucket": canonical,
        "source_buckets": buckets,
        "disagreement_sources": disagreement_sources,
        "source_disagreement_count": len(disagreement_sources),
        "alternate_buckets": alternate_buckets,
        "alternate_label_sensitivity_status": (
            "CHANGES_RESULT" if alternate_changes else "NO_ALTERNATE_LABEL"
        ),
        "alternate_label_changes_result": alternate_changes,
        "lineage_status": lineage["status"],
        "lineage_hashed_source_count": lineage["hashed_source_count"],
        "lineage_missing_with_reason_count": lineage["missing_with_reason_count"],
        "lineage": lineage["entries"],
        "note": row.get("note") or "",
        "finalized_at_utc": row.get("finalized_at_utc") or "",
    }


@contextmanager
def open_settlement_source_audit(
    *,
    labels_csv=DEFAULT_LABELS_CSV,
    ledger_root=DEFAULT_LEDGER_ROOT,
    generated_at_utc=None,
    scratch_root=None,
    max_index_bytes=DEFAULT_MAX_INDEX_BYTES,
    cancelled=None,
    sealed_lineage_sha256=(),
):
    """Build a repeatable, disk-backed audit valid within the returned context.

    The index is new for every invocation, so late revisions and label
    corrections are reconsidered. Live lineage files are hashed directly;
    their mtimes are never treated as immutable content identities. Offline
    callers may supply an iterable of (absolute_path, expected_sha256) pairs
    for a sealed corpus; these identities are verified against actual bytes.
    """
    with AuditStore(scratch_root=scratch_root, max_index_bytes=max_index_bytes,
                    cancelled=cancelled) as store:
        hashes = SealedLineageHashes(store, sealed_lineage_sha256, _sha256)
        store.verify_lineage = hashes.verify
        store.load(labels_csv, ledger_root)
        status_counts = Counter()
        by_market = defaultdict(Counter)
        lag_by_market = {}
        disagreements = Counter()
        proof_count = blocked_count = alternate_count = missing_lineage_count = 0
        for source_row in store.merged_rows():
            row = audit_row(source_row, sha256=hashes)
            store.add_audited_row(row)
            status_counts[row["status"]] += 1
            market_id = row.get("market_id") or "unknown"
            if market_id not in by_market and len(by_market) >= 4096:
                raise ValueError("Audit market-summary group limit exceeded")
            by_market[market_id][row["status"]] += 1
            if row.get("finalization_lag_hours") is not None:
                lag = row["finalization_lag_hours"]
                lag_by_market[market_id] = max(lag, lag_by_market.get(market_id, lag))
            # Preserve the legacy unknown-market summary: absent/empty IDs
            # group as unknown, but only an explicit "unknown" ID contributes
            # to that group's disagreement count.
            if row.get("market_id") == market_id and row.get("source_disagreement_count"):
                disagreements[market_id] += 1
            proof_count += bool(row.get("proof_grade_label"))
            blocked_count += bool(row.get("promotion_blocker"))
            alternate_count += bool(row.get("alternate_label_changes_result"))
            missing_lineage_count += row.get("lineage_missing_with_reason_count") or 0
        hashes.verify()
        rows = store.finish()
        market_rows = [{
            "market_id": market_id,
            "label_count": sum(by_market[market_id].values()),
            "finalized_count": by_market[market_id].get("FINALIZED", 0),
            "uncertain_count": sum(count for status, count in by_market[market_id].items()
                                   if status in UNCERTAIN_STATUSES),
            "source_disagreement_count": disagreements[market_id],
            "max_finalization_lag_hours": lag_by_market.get(market_id),
            "status_counts": dict(sorted(by_market[market_id].items())),
        } for market_id in sorted(by_market)]
        yield {
            "schema_version": SCHEMA_VERSION,
            "generated_at_utc": generated_at_utc or _utc_iso(),
            "labels_csv": str(labels_csv),
            "ledger_root": str(ledger_root),
            "status": "MISSING" if not rows else ("BLOCK" if blocked_count else "PASS"),
            "summary": {
                "label_count": len(rows),
                "finalized_label_count": status_counts.get("FINALIZED", 0),
                "provisional_label_count": status_counts.get("PROVISIONAL", 0),
                "revised_label_count": status_counts.get("SOURCE_REVISION", 0),
                "source_disagreement_label_count": status_counts.get("SOURCE_DISAGREEMENT", 0),
                "manual_override_label_count": status_counts.get("MANUAL_OVERRIDE", 0),
                "unreconciled_label_count": status_counts.get("UNRECONCILED", 0),
                "source_stale_label_count": status_counts.get("SOURCE_STALE", 0),
                "proof_grade_label_count": proof_count,
                "promotion_blocked_label_count": blocked_count,
                "alternate_label_changes_result_count": alternate_count,
                "lineage_missing_with_reason_count": missing_lineage_count,
                "status_counts": dict(sorted(status_counts.items())),
            },
            "by_market": market_rows,
            "rows": rows,
        }


def build_settlement_source_audit(
    *,
    labels_csv=DEFAULT_LABELS_CSV,
    ledger_root=DEFAULT_LEDGER_ROOT,
    generated_at_utc=None,
):
    """Materialized compatibility API for small callers and existing fixtures.

    Production builders and consumers use open_settlement_source_audit so the
    final row set is not brought back into memory after indexed selection.
    """
    with open_settlement_source_audit(labels_csv=labels_csv, ledger_root=ledger_root,
                                     generated_at_utc=generated_at_utc) as payload:
        return {**payload, "rows": list(payload["rows"])}


def settlement_label_gate_for_target_dates(payload, target_dates):
    target_dates = sorted({str(value) for value in (target_dates or []) if value})
    if not target_dates:
        return {
            "status": "SKIP",
            "target_dates": [],
            "blocked_target_dates": [],
            "blockers": [],
            "reason": "no settlement-scored target dates",
        }
    source_rows = (payload or {}).get("rows")
    has_rows = bool(source_rows) if hasattr(source_rows, "__len__") else False
    selected = set(target_dates)
    if hasattr(source_rows, "iter_target_dates"):
        rows = source_rows.iter_target_dates(target_dates)
    else:
        rows = source_rows if source_rows is not None else ()
    present = set()
    bad_by_date = defaultdict(list)
    reconciled_by_date = defaultdict(list)
    # Exhaust a file-backed iterator even after finding the requested dates.
    # A truncated or malformed tail must invalidate the entire file.
    for row in rows:
        has_rows = True
        target_date = str(row.get("target_date") or "")
        if target_date not in selected:
            continue
        present.add(target_date)
        if not row.get("promotion_blocker"):
            continue
        if str(row.get("reconciliation_status") or "").strip().lower() == "match":
            reconciled_by_date[target_date].append(
                f"{target_date}:{row.get('market_id') or 'unknown'}:"
                f"{row.get('promotion_blocker_reason') or row.get('status')}"
            )
        else:
            bad_by_date[target_date].append(
                f"{target_date}:{row.get('market_id') or 'unknown'}:{row.get('status')}"
            )
    if not has_rows:
        return {
            "status": "BLOCK",
            "target_dates": target_dates,
            "blocked_target_dates": target_dates,
            "blockers": ["settlement_source_audit_missing"],
            "reason": "settlement-scored evidence has no truth-label audit rows",
        }
    blockers = []
    blocked_dates = []
    non_countable_reconciled = []
    for target_date in target_dates:
        if target_date not in present:
            blocked_dates.append(target_date)
            blockers.append(f"{target_date}:missing_audit_row")
            continue
        non_countable_reconciled.extend(reconciled_by_date[target_date])
        if bad_by_date[target_date]:
            blocked_dates.append(target_date)
            blockers.extend(bad_by_date[target_date])
    return {
        "status": "BLOCK" if blockers else "PASS",
        "target_dates": target_dates,
        "blocked_target_dates": blocked_dates,
        "blockers": blockers,
        "non_countable_reconciled": non_countable_reconciled,
        "reason": "truth-label uncertainty blocks promotion-grade evidence" if blockers else "truth labels proof-grade",
    }


def settlement_label_gate_from_path(path, target_dates):
    """Read the legacy JSON with bounded memory and validate its complete tail."""
    reader = AuditJsonRows(path) if path else None
    try:
        gate = settlement_label_gate_for_target_dates({"rows": reader}, target_dates)
    except (OSError, ValueError, UnicodeError, RecursionError):
        reader = None
        gate = settlement_label_gate_for_target_dates({}, target_dates)
    gate["path"] = str(path) if path else None
    gate["audit_status"] = reader.metadata.get("status") if reader and reader.has_fields else "MISSING"
    return gate


def render_report(payload):
    summary = payload.get("summary") or {}
    lines = [
        "# Settlement Source Revision Audit",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: **{payload.get('status')}**",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Labels", summary.get("label_count")],
            ["Finalized", summary.get("finalized_label_count")],
            ["Provisional", summary.get("provisional_label_count")],
            ["Revised", summary.get("revised_label_count")],
            ["Source disagreement", summary.get("source_disagreement_label_count")],
            ["Manual overrides", summary.get("manual_override_label_count")],
            ["Unreconciled", summary.get("unreconciled_label_count")],
            ["Proof-grade", summary.get("proof_grade_label_count")],
            ["Promotion blocked", summary.get("promotion_blocked_label_count")],
            ["Alternate-label changes result", summary.get("alternate_label_changes_result_count")],
        ],
    )
    lines += ["", "## By Market", ""]
    lines += markdown_table(
        ["Market", "Labels", "Finalized", "Uncertain", "Disagreements", "Max Finalization Lag Hours"],
        [
            [
                row.get("market_id"),
                row.get("label_count"),
                row.get("finalized_count"),
                row.get("uncertain_count"),
                row.get("source_disagreement_count"),
                row.get("max_finalization_lag_hours"),
            ]
            for row in payload.get("by_market") or []
        ],
    )
    blockers = []
    for row in payload.get("rows") or []:
        if row.get("promotion_blocker"):
            blockers.append(row)
            if len(blockers) == 50:
                break
    if blockers:
        lines += ["", "## Promotion Blockers", ""]
        lines += markdown_table(
            ["Date", "Market", "Status", "Canonical", "Disagreement Sources", "Alternate Sensitivity"],
            [
                [
                    row.get("target_date"),
                    row.get("market_id"),
                    row.get("status"),
                    row.get("canonical_settlement_bucket"),
                    ", ".join(row.get("disagreement_sources") or []) or "-",
                    row.get("alternate_label_sensitivity_status"),
                ]
                for row in blockers[:50]
            ],
        )
    lines.append("")
    return "\n".join(lines)


def write_outputs(payload, json_out=DEFAULT_JSON_OUT, report_out=DEFAULT_REPORT_OUT,
                  *, max_output_bytes=DEFAULT_MAX_OUTPUT_BYTES):
    """Stage both representations and atomically publish complete files.

    JSON remains the authoritative gate input and is replaced last. Markdown
    is advisory; the pair is not a multi-file publication transaction.
    """
    json_path = Path(json_out)
    report_path = Path(report_out)
    if json_path.resolve() == report_path.resolve():
        raise ValueError("Audit JSON and Markdown require distinct output paths")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    rows = payload.get("rows")
    with ExitStack() as cleanup:
        json_dir = Path(cleanup.enter_context(tempfile.TemporaryDirectory(
            prefix=".settlement-audit-", dir=json_path.parent)))
        report_dir = Path(cleanup.enter_context(tempfile.TemporaryDirectory(
            prefix=".settlement-audit-", dir=report_path.parent)))
        staged_json = json_dir / "audit.json"
        staged_report = report_dir / "audit.md"
        write_json_streaming_atomic(staged_json, payload, trailing_newline=True,
                                    max_bytes=max_output_bytes)
        write_text_atomic(staged_report, render_report(payload))
        if hasattr(rows, "check_cancelled"):
            rows.check_cancelled()
        if hasattr(rows, "verify_lineage"):
            rows.verify_lineage()
        staged_report.replace(report_path)
        staged_json.replace(json_path)
    return json_path, report_path


def build_parser():
    parser = argparse.ArgumentParser(description="Build settlement-source revision audit.")
    parser.add_argument("--labels-csv", default=str(DEFAULT_LABELS_CSV))
    parser.add_argument("--ledger-root", default=str(DEFAULT_LEDGER_ROOT))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--scratch-root", default=None, help="Parent for this invocation\'s disposable disk index.")
    parser.add_argument("--max-index-bytes", type=int, default=DEFAULT_MAX_INDEX_BYTES)
    parser.add_argument("--max-output-bytes", type=int, default=DEFAULT_MAX_OUTPUT_BYTES)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    with open_settlement_source_audit(
        labels_csv=args.labels_csv,
        ledger_root=args.ledger_root,
        scratch_root=args.scratch_root,
        max_index_bytes=args.max_index_bytes,
    ) as payload:
        json_out, report_out = write_outputs(
            payload, args.json_out, args.report_out, max_output_bytes=args.max_output_bytes,
        )
        status = payload.get("status")
    print(f"Settlement source audit: {status}")
    print(f"JSON written to {json_out}")
    print(f"Report written to {report_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
