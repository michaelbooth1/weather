"""Mechanical maker-day countability checklist.

Every input is retained evidence. Missing tapes, incomplete WebSocket coverage,
missing settlement on a fill, or a heuristic reward denominator fails closed.
"""

from __future__ import annotations

import json
import hashlib
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

from weather.market.mm_policy import parse_time
from weather.market.mm_paper_constants import EXECUTION_SESSION_FILENAME
from weather.paths import docs_path
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("mm_day_countability")
TAPE_INVENTORY_SCHEMA_VERSION = schema_version("mm_execution_tape_inventory")
SESSION_FILENAME = EXECUTION_SESSION_FILENAME
DEFAULT_RESERVATION_PATH = docs_path("operations", "reserved-confirmation-window.md")
_RESERVED_ROW = re.compile(
    r"^\|\s*\*\*Reserved dates\*\*\s*\|(?P<value>.*?)\|\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def confirmation_reservation_gate(target_date=None, *, path=DEFAULT_RESERVATION_PATH):
    """Fail closed on a declared confirmation date before MM evidence is read."""

    source = Path(path)
    try:
        raw = source.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {
            "status": "BLOCK",
            "state": "SOURCE_UNREADABLE",
            "target_date": str(target_date) if target_date else None,
            "source_path": str(source),
            "source_sha256": None,
            "blockers": [f"reservation_source_unreadable:{type(exc).__name__}"],
        }
    binding = hashlib.sha256(raw).hexdigest()
    match = _RESERVED_ROW.search(text)
    if match is None:
        return {
            "status": "BLOCK",
            "state": "SOURCE_UNPARSEABLE",
            "target_date": str(target_date) if target_date else None,
            "source_path": str(source),
            "source_sha256": binding,
            "blockers": ["reserved_dates_row_missing"],
        }
    value = match.group("value").strip()
    if "NONE ARE CURRENTLY RESERVED" in value.upper():
        return {
            "status": "PASS",
            "state": "ARMED_UNDATED",
            "target_date": str(target_date) if target_date else None,
            "source_path": str(source),
            "source_sha256": binding,
            "reserved_start": None,
            "reserved_end": None,
            "blockers": [],
        }
    dates = _ISO_DATE.findall(value)
    if len(dates) not in {1, 2}:
        return {
            "status": "BLOCK",
            "state": "DECLARATION_UNPARSEABLE",
            "target_date": str(target_date) if target_date else None,
            "source_path": str(source),
            "source_sha256": binding,
            "blockers": ["reserved_dates_declaration_unparseable"],
        }
    try:
        reserved_start = date.fromisoformat(dates[0])
        reserved_end = date.fromisoformat(dates[-1])
    except ValueError:
        return {
            "status": "BLOCK",
            "state": "DECLARATION_UNPARSEABLE",
            "target_date": str(target_date) if target_date else None,
            "source_path": str(source),
            "source_sha256": binding,
            "blockers": ["reserved_dates_declaration_unparseable"],
        }
    if reserved_end < reserved_start:
        return {
            "status": "BLOCK",
            "state": "DECLARATION_UNPARSEABLE",
            "target_date": str(target_date) if target_date else None,
            "source_path": str(source),
            "source_sha256": binding,
            "blockers": ["reserved_dates_range_reversed"],
        }
    if not target_date:
        return {
            "status": "BLOCK",
            "state": "DECLARED_TARGET_REQUIRED",
            "target_date": None,
            "source_path": str(source),
            "source_sha256": binding,
            "reserved_start": reserved_start.isoformat(),
            "reserved_end": reserved_end.isoformat(),
            "blockers": ["explicit_target_required_while_confirmation_reserved"],
        }
    try:
        target = date.fromisoformat(str(target_date))
    except ValueError:
        return {
            "status": "BLOCK",
            "state": "TARGET_UNPARSEABLE",
            "target_date": str(target_date),
            "source_path": str(source),
            "source_sha256": binding,
            "reserved_start": reserved_start.isoformat(),
            "reserved_end": reserved_end.isoformat(),
            "blockers": ["reservation_target_date_unparseable"],
        }
    blocked = reserved_start <= target <= reserved_end
    return {
        "status": "BLOCK" if blocked else "PASS",
        "state": "DECLARED_RESERVED" if blocked else "DECLARED_OUTSIDE_TARGET",
        "target_date": target.isoformat(),
        "source_path": str(source),
        "source_sha256": binding,
        "reserved_start": reserved_start.isoformat(),
        "reserved_end": reserved_end.isoformat(),
        "blockers": ["target_date_reserved_for_confirmation"] if blocked else [],
    }


def _nonempty(path):
    try:
        return path.exists() and path.stat().st_size > 0
    except OSError:
        return False


def _sessions(path):
    rows = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            start = parse_time(row.get("coverage_start_utc"))
            end = parse_time(row.get("coverage_end_utc"))
            if start is None or end is None:
                continue
            rows.append({**row, "_start": start, "_end": end})
    return rows


def build_execution_tape_inventory(quote_rows, legs, snapshots_root):
    by_event = defaultdict(lambda: {
        "target_dates": set(),
        "decision_row_count": 0,
        "uncovered_decision_count": 0,
        "uncovered_decision_examples": [],
        "quote_leg_count": 0,
        "uncovered_count": 0,
        "uncovered_examples": [],
    })
    session_cache = {}
    for row in quote_rows or []:
        event_slug = str(row.get("event_slug") or "")
        if event_slug:
            by_event[event_slug]["target_dates"].add(str(row.get("target_date") or ""))
            by_event[event_slug]["decision_row_count"] += 1
            if event_slug not in session_cache:
                session_cache[event_slug] = _sessions(
                    Path(snapshots_root) / event_slug / SESSION_FILENAME
                )
            decision_time = parse_time(
                row.get("generated_at_utc") or row.get("captured_at_utc")
            )
            covered = bool(
                decision_time is not None and any(
                    session.get("status") == "COMPLETE"
                    and bool(session.get("continuous_coverage"))
                    and session["_start"] <= decision_time <= session["_end"]
                    for session in session_cache[event_slug]
                )
            )
            if not covered:
                by_event[event_slug]["uncovered_decision_count"] += 1
                if len(by_event[event_slug]["uncovered_decision_examples"]) < 100:
                    by_event[event_slug]["uncovered_decision_examples"].append(
                        str(row.get("_quote_id") or row.get("quote_id") or "unknown")
                    )
    for leg in legs or []:
        event_slug = str(leg.get("event_slug") or "")
        if event_slug:
            by_event[event_slug]["target_dates"].add(str(leg.get("target_date") or ""))
            by_event[event_slug]["quote_leg_count"] += 1
            if event_slug not in session_cache:
                session_cache[event_slug] = _sessions(
                    Path(snapshots_root) / event_slug / SESSION_FILENAME
                )
            complete_sessions = [
                row for row in session_cache[event_slug]
                if row.get("status") == "COMPLETE" and bool(row.get("continuous_coverage"))
            ]
            start = leg.get("quote_time")
            end = leg.get("quote_expires_at")
            covered = bool(
                start is not None and end is not None and any(
                    session["_start"] <= start and session["_end"] >= end
                    for session in complete_sessions
                )
            )
            if not covered:
                by_event[event_slug]["uncovered_count"] += 1
                if len(by_event[event_slug]["uncovered_examples"]) < 100:
                    by_event[event_slug]["uncovered_examples"].append(
                        str(leg.get("leg_id") or "unknown")
                    )

    event_rows = []
    blockers = []
    for event_slug, expected in sorted(by_event.items()):
        folder = Path(snapshots_root) / event_slug
        book_path = folder / "order_books.jsonl"
        raw_path = folder / "market_ws.jsonl"
        csv_path = folder / "market_ws_events.csv"
        session_path = folder / SESSION_FILENAME
        sessions = session_cache.get(event_slug)
        if sessions is None:
            sessions = _sessions(session_path)
        complete_sessions = [
            row for row in sessions
            if row.get("status") == "COMPLETE" and bool(row.get("continuous_coverage"))
        ]
        tape_present = _nonempty(raw_path) and _nonempty(csv_path)
        full_depth_book_tape_present = _nonempty(book_path)
        if not full_depth_book_tape_present:
            blockers.append(f"full_depth_book_tape_missing:{event_slug}")
        if not tape_present:
            blockers.append(f"execution_tape_missing:{event_slug}")
        if not complete_sessions:
            blockers.append(f"execution_session_coverage_missing:{event_slug}")
        uncovered_decision_count = expected["uncovered_decision_count"]
        if uncovered_decision_count:
            blockers.append(
                f"decision_time_not_covered:{event_slug}={uncovered_decision_count}"
            )
        uncovered_count = expected["uncovered_count"]
        if uncovered_count:
            blockers.append(
                f"quote_lifetime_not_covered:{event_slug}={uncovered_count}"
            )
        event_rows.append({
            "event_slug": event_slug,
            "target_dates": sorted(value for value in expected["target_dates"] if value),
            "order_books_jsonl_path": str(book_path),
            "full_depth_book_tape_present": full_depth_book_tape_present,
            "market_ws_jsonl_path": str(raw_path),
            "market_ws_events_csv_path": str(csv_path),
            "session_receipt_path": str(session_path),
            "execution_tape_present": tape_present,
            "session_receipt_count": len(sessions),
            "complete_session_count": len(complete_sessions),
            "decision_row_count": expected["decision_row_count"],
            "uncovered_decision_count": uncovered_decision_count,
            "uncovered_decision_ids": expected["uncovered_decision_examples"],
            "quote_leg_count": expected["quote_leg_count"],
            "uncovered_quote_leg_count": uncovered_count,
            "uncovered_quote_leg_ids": expected["uncovered_examples"],
        })
    return {
        "schema_version": TAPE_INVENTORY_SCHEMA_VERSION,
        "status": "PASS" if event_rows and not blockers else "BLOCK",
        "expected_event_count": len(event_rows),
        "blockers": sorted(set(blockers or (["no_expected_events"] if not event_rows else []))),
        "events": event_rows,
    }


def build_day_countability(
    quote_rows,
    legs,
    fill_rows,
    *,
    snapshots_root,
    fill_evidence,
    reward_q_share,
    target_date=None,
    reservation_gate=None,
):
    selected_target = str(target_date) if target_date else None

    def selected(rows):
        return (
            row for row in rows or []
            if selected_target is None
            or str(row.get("target_date") or "") == selected_target
        )

    if selected_target is not None:
        target_dates = [selected_target]
    else:
        target_dates = set()
        for rows in (quote_rows or [], legs or [], fill_rows or []):
            for row in rows:
                if row.get("target_date"):
                    target_dates.add(str(row["target_date"]))
        target_dates = sorted(target_dates)
    tape = build_execution_tape_inventory(
        selected(quote_rows),
        selected(legs),
        snapshots_root,
    )
    blockers = list(tape.get("blockers") or [])
    reservation_gate = reservation_gate or {
        "status": "BLOCK",
        "blockers": ["reservation_gate_missing"],
    }
    if reservation_gate.get("status") != "PASS":
        blockers.extend(
            f"reservation:{blocker}"
            for blocker in reservation_gate.get("blockers") or ["blocked"]
        )
    if len(target_dates) != 1:
        blockers.append("expected_exactly_one_target_date")
    settlement_missing_count = 0
    settlement_missing_ids = []
    non_strict_fill_count = 0
    incomplete_execution_fill_count = 0
    missing_markout_fill_count = 0
    missing_markout_ids = []
    fill_count = 0
    for row in selected(fill_rows):
        fill_count += 1
        if row.get("conservative_fill_rule") != "strict_trade_through_price_and_recorded_size":
            non_strict_fill_count += 1
        required_execution_values = (
            row.get("execution_exchange_time_utc"),
            row.get("execution_time_precision_seconds"),
            row.get("clob_token_id"),
            row.get("execution_condition_id"),
            row.get("execution_side"),
            row.get("through_trade_price"),
            row.get("through_trade_size"),
            row.get("execution_raw_sha1"),
            row.get("canonical_execution_id") or row.get("execution_id"),
        )
        if any(value is None or value == "" for value in required_execution_values):
            incomplete_execution_fill_count += 1
        if any(
            row.get(field) is None or row.get(field) == ""
            for field in (
                "markout_30s_per_share",
                "markout_1m_per_share",
                "markout_5m_per_share",
                "markout_30m_per_share",
            )
        ):
            missing_markout_fill_count += 1
            if len(missing_markout_ids) < 100:
                missing_markout_ids.append(str(row.get("fill_id") or "unknown"))
        if row.get("acceptance_pnl_status") != "COUNTABLE_SETTLEMENT":
            settlement_missing_count += 1
            if len(settlement_missing_ids) < 100:
                settlement_missing_ids.append(str(row.get("fill_id") or "unknown"))
    if settlement_missing_count:
        blockers.append(f"settlement_horizon_missing={settlement_missing_count}")
    if non_strict_fill_count:
        blockers.append(f"non_strict_through_fills={non_strict_fill_count}")
    if incomplete_execution_fill_count:
        blockers.append(
            f"execution_provenance_incomplete_fills={incomplete_execution_fill_count}"
        )
    if missing_markout_fill_count:
        blockers.append(f"required_markout_horizons_missing={missing_markout_fill_count}")
    target_fill_evidence = fill_evidence or {}
    if selected_target is not None:
        target_fill_evidence = (
            (fill_evidence or {}).get("by_target_date") or {}
        ).get(selected_target) or fill_evidence or {}
    fill_blockers = [
        blocker for blocker in target_fill_evidence.get("blockers") or []
        if blocker != "no_quote_legs"
    ]
    blockers.extend(f"fill_evidence:{blocker}" for blocker in fill_blockers)
    selected_leg_count = sum(1 for _row in selected(legs))
    target_reward_q_share = reward_q_share or {}
    if selected_target is not None:
        target_reward_q_share = (
            (reward_q_share or {}).get("by_target_date") or {}
        ).get(selected_target) or {
            "status": "NOT_APPLICABLE" if selected_leg_count == 0 else "BLOCK",
            "exact_sampled": selected_leg_count == 0,
            "quoted_legs": selected_leg_count,
            "sampled_legs": 0,
            "blockers": [] if selected_leg_count == 0 else ["target_date_samples_missing"],
        }
    reward_status = target_reward_q_share.get("status")
    if selected_leg_count and (
        reward_status != "PASS"
        or not bool(target_reward_q_share.get("exact_sampled"))
    ):
        blockers.append("reward_q_share_not_exact")
    blockers = sorted(set(blockers))
    status = "COUNTABLE" if not blockers else "NOT_COUNTABLE"
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "counts_toward_maker_day_target": status == "COUNTABLE",
        "target_dates": target_dates,
        "checklist": {
            "exactly_one_target_date": len(target_dates) == 1,
            "confirmation_reservation_clear": reservation_gate.get("status") == "PASS",
            "execution_tape_present": tape.get("status") == "PASS",
            "full_depth_book_tape_present": not any(
                blocker.startswith("full_depth_book_tape_missing:") for blocker in blockers
            ),
            "decision_times_continuously_covered": not any(
                blocker.startswith("decision_time_not_covered:") for blocker in blockers
            ),
            "quote_lifetimes_continuously_covered": not any(
                blocker.startswith("quote_lifetime_not_covered:") for blocker in blockers
            ),
            "strict_through_only": non_strict_fill_count == 0,
            "execution_provenance_complete": incomplete_execution_fill_count == 0,
            "all_required_markouts_complete": missing_markout_fill_count == 0,
            "settlement_horizon_complete": settlement_missing_count == 0,
            "fill_evidence_complete": not fill_blockers,
            "reward_q_share_exact_when_quoted": not selected_leg_count or reward_status == "PASS",
        },
        "blockers": blockers,
        "first_blocker": blockers[0] if blockers else None,
        "quote_rows": sum(1 for _row in selected(quote_rows)),
        "quote_legs": selected_leg_count,
        "strict_through_fills": fill_count,
        "non_strict_through_fill_count": non_strict_fill_count,
        "execution_provenance_incomplete_fill_count": incomplete_execution_fill_count,
        "required_markout_missing_fill_count": missing_markout_fill_count,
        "required_markout_missing_fill_ids": missing_markout_ids,
        "settlement_missing_fill_count": settlement_missing_count,
        "settlement_missing_fill_ids": settlement_missing_ids,
        "execution_tape_inventory": tape,
        "reward_q_share_status": reward_status,
        "reward_q_share": target_reward_q_share,
        "fill_evidence": target_fill_evidence,
        "confirmation_reservation_gate": reservation_gate,
    }
