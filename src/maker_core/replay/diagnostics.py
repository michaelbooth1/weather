"""Deterministic capture coverage; no decisions, fills, P&L or policy comparisons."""
from collections import Counter
from datetime import timedelta
from pathlib import Path

from maker_core.evidence.journal import canonical_bytes
from maker_core.replay.bundle import Bundle, BundleError, regular_path

REPORT_FORMAT = "maker_core.replay.diagnostics.v0.1"
MAX_REPORT_BYTES = 8 * 1024**2
ASSUMPTIONS = (
    "Public trades do not prove our fills or queue position.",
    "Minute books hide intervening price paths and cancellations.",
    "Capture gaps are exclusions; no reward, fill or return zero is imputed.",
    "Envelope hashes prove byte binding, not source truth or owner authorization.",
    "Diagnostic mode checks envelopes; it does not execute a policy or validate economic eligibility.",
)


def coverage_report(bundle: Bundle, policy: str, *, check=lambda: None) -> dict:
    by_condition = {c.condition_id: Counter() for c in bundle.conditions}
    book_minutes = {c.condition_id: set() for c in bundle.conditions}
    for record in bundle.records:
        check()
        by_condition[record.condition_id][record.kind] += 1
        if record.kind == "book":
            book_minutes[record.condition_id].add(record.captured_at.replace(second=0, microsecond=0))
    coverage = []
    for condition in bundle.conditions:
        check()
        cursor, exclusions = condition.active_from, []
        observed = sorted(t for t in book_minutes[condition.condition_id]
                          if condition.active_from <= t < condition.active_until)
        for minute in observed:
            check()
            if minute > cursor:
                exclusions.append({"from": cursor, "until": minute, "reason": "MISSING_BOOK_CAPTURE"})
            cursor = minute + timedelta(minutes=1)
        if cursor < condition.active_until:
            exclusions.append({"from": cursor, "until": condition.active_until,
                               "reason": "MISSING_BOOK_CAPTURE"})
        expected = int((condition.active_until - condition.active_from).total_seconds() / 60)
        coverage.append({"condition_id": condition.condition_id, "market_id": condition.market_id,
                         "domain_id": condition.domain_id, "expected_minutes": expected,
                         "book_capture_minutes": len(observed), "excluded_minutes": expected - len(observed),
                         "record_counts": dict(sorted(by_condition[condition.condition_id].items())),
                         "exclusions": exclusions, "evaluable_minutes": None})
    return {"format": REPORT_FORMAT, "mode": "diagnostic-only", "status": "DIAGNOSTIC_ONLY",
            "day": bundle.day.isoformat(), "provenance": bundle.provenance,
            "requested_policy": policy, "policy_executed": False, "input_hashes": bundle.input_hashes,
            "input_bytes": bundle.input_bytes, "records": len(bundle.records), "coverage": coverage,
            "parity": {"status": "NOT_RUN", "reason": "no sanitized full-session journal supplied"},
            "assumptions": ASSUMPTIONS}


def report_bytes(report: dict) -> tuple[bytes, bytes]:
    raw = canonical_bytes(report)
    lines = ["# Maker replay diagnostics", "", "**DIAGNOSTIC_ONLY — no policy comparison or score.**", "",
             f"Closed UTC day: {report['day']}. Records: {report['records']}.", "",
             "Book capture coverage is not decision eligibility. Payload semantics remain unchecked.", "",
             "| Condition | Expected minutes | Book capture minutes | Excluded minutes |",
             "| --- | ---: | ---: | ---: |"]
    for row in report["coverage"]:
        label = str(row['condition_id']).replace("|", "&#124;").replace("<", "&lt;")
        lines.append(f"| {label} | {row['expected_minutes']} | {row['book_capture_minutes']} | {row['excluded_minutes']} |")
    lines.extend(["", "Parity: NOT_RUN; no sanitized full-session journal supplied.", "", "Assumptions:", ""])
    lines.extend("- " + assumption for assumption in report["assumptions"])
    lines.extend(["", "Input SHA-256 hashes:", ""])
    lines.extend(f"- `{name}`: `{value}`" for name, value in sorted(report["input_hashes"].items()))
    return raw, ("\n".join(lines) + "\n").encode("utf-8")


def write_report(directory: Path, report: dict, *, input_directory: Path,
                 max_bytes: int = MAX_REPORT_BYTES, check=lambda: None, render=report_bytes,
                 other_inputs=()) -> None:
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_REPORT_BYTES:
        raise BundleError("invalid_report_byte_cap")
    check()
    output, source = regular_path(directory), regular_path(input_directory)
    if output == source or output.is_relative_to(source) or source.is_relative_to(output):
        raise BundleError("output_input_overlap")
    for path in other_inputs:
        source = regular_path(path)
        if output == source or output.is_relative_to(source) or source.is_relative_to(output):
            raise BundleError("output_input_overlap")
    raw, markdown = render(report)
    if len(raw) + len(markdown) > max_bytes:
        raise BundleError("report_byte_cap")
    check()
    # New directory only. Failed writes leave a visible partial directory;
    # neither inputs nor existing reports are ever overwritten or removed.
    output.mkdir(parents=False, exist_ok=False)
    with (output / "report.json").open("xb") as handle:
        handle.write(raw)
    with (output / "report.md").open("xb") as handle:
        handle.write(markdown)
