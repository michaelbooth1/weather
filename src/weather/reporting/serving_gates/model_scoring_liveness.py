"""Shared liveness checks for settlement-scored model artifacts."""

from __future__ import annotations

import csv
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

from weather.market.market_config import date_from_event_slug


DEFAULT_QUALITY_GRADES = ("complete", "manual_override")
LIVENESS_BLOCKER_GATE = "model_scoring_liveness_stale"


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "pass", "countable"}


def parse_quality_grades(value: Any, *, default: tuple[str, ...] = DEFAULT_QUALITY_GRADES) -> tuple[str, ...]:
    if value in (None, ""):
        return tuple(default)
    if isinstance(value, str):
        parsed = [item.strip() for item in value.split(",") if item.strip()]
    else:
        parsed = [str(item).strip() for item in value if str(item).strip()]
    return tuple(parsed or default)


def date_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return None
    candidate = text[:10]
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError:
        return None


def read_label_rows(labels_csv: str | Path) -> list[dict[str, Any]]:
    path = Path(labels_csv)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def row_target_date(row: dict[str, Any]) -> str | None:
    target = date_text(row.get("target_date"))
    if target:
        return target
    try:
        parsed = date_from_event_slug(row.get("event_slug"))
    except Exception:  # pragma: no cover - malformed slug fallback
        parsed = None
    return parsed.isoformat() if parsed else None


def latest_settled_label_summary(
    labels_csv: str | Path,
    *,
    quality_grades: Any = DEFAULT_QUALITY_GRADES,
    include_promotion_countable_labels: bool = True,
) -> dict[str, Any]:
    grades = parse_quality_grades(quality_grades)
    allowed = {grade.lower() for grade in grades}
    allow_all = "all" in allowed
    rows = read_label_rows(labels_csv)
    selected: list[dict[str, Any]] = []
    quality_counts = Counter()
    selected_quality_counts = Counter()
    selected_promotion_countable_count = 0
    selected_by_reason = Counter()
    by_date = Counter()
    for row in rows:
        quality = str(row.get("quality_grade") or "unknown")
        quality_counts[quality] += 1
        quality_allowed = allow_all or quality.lower() in allowed
        promotion_countable = truthy(row.get("promotion_countable"))
        if not quality_allowed and not (include_promotion_countable_labels and promotion_countable):
            continue
        target = row_target_date(row)
        if not target:
            continue
        selected.append(row)
        selected_quality_counts[quality] += 1
        if promotion_countable:
            selected_promotion_countable_count += 1
            selected_by_reason[str(row.get("promotion_countable_reason") or "-")] += 1
        by_date[target] += 1
    latest = max(by_date, default=None)
    return {
        "labels_csv": str(Path(labels_csv)),
        "labels_csv_exists": Path(labels_csv).exists(),
        "quality_grades": list(grades),
        "include_promotion_countable_labels": bool(include_promotion_countable_labels),
        "selected_label_count": len(selected),
        "latest_settled_label_date": latest,
        "latest_label_count": by_date.get(latest, 0) if latest else 0,
        "date_counts": dict(sorted(by_date.items())),
        "quality_counts": dict(sorted(quality_counts.items())),
        "selected_quality_counts": dict(sorted(selected_quality_counts.items())),
        "selected_promotion_countable_label_count": selected_promotion_countable_count,
        "selected_promotion_countable_reasons": dict(sorted(selected_by_reason.items())),
    }


def last_scored_target_date_from_payload(payload: dict[str, Any]) -> str | None:
    corpus = (payload or {}).get("corpus") or {}
    return date_text(
        (payload or {}).get("last_scored_target_date")
        or (payload or {}).get("target_date")
        or corpus.get("date_max")
    )


def build_rerun_command(
    module: str,
    *,
    labels_csv: str | Path | None = None,
    snapshots_root: str | Path | None = None,
    quality_grades: Any = DEFAULT_QUALITY_GRADES,
    include_promotion_countable_labels: bool = True,
    markets: Any = None,
    start_date: Any = None,
    end_date: Any = None,
    extra_args: list[Any] | tuple[Any, ...] | None = None,
) -> str:
    parts = ["python", "-m", module]
    if labels_csv is not None:
        parts += ["--labels-csv", str(labels_csv)]
    if snapshots_root is not None:
        parts += ["--snapshots-root", str(snapshots_root)]
    grades = parse_quality_grades(quality_grades)
    if grades:
        parts += ["--quality-grades", ",".join(grades)]
    if not include_promotion_countable_labels:
        parts += ["--strict-quality-grades-only"]
    if markets not in (None, "", []):
        if isinstance(markets, str):
            market_text = markets
        else:
            market_text = ",".join(str(item) for item in markets if str(item).strip())
        if market_text:
            parts += ["--markets", market_text]
    if start_date:
        parts += ["--start-date", str(start_date)]
    if end_date:
        parts += ["--end-date", str(end_date)]
    if extra_args:
        parts.extend(str(item) for item in extra_args if item not in (None, ""))
    return " ".join(_quote_part(part) for part in parts)


def build_root_cause_rerun_command(
    *,
    target_date: str,
    snapshots_root: str | Path | None = None,
    taker_root: str | Path | None = None,
    mm_root: str | Path | None = None,
    backtest_root: str | Path | None = None,
    labels_csv: str | Path | None = None,
) -> str:
    parts = ["python", "-m", "weather.reporting.scorecards.settled_day_root_cause", "--date", str(target_date)]
    if snapshots_root is not None:
        parts += ["--snapshots-root", str(snapshots_root)]
    if taker_root is not None:
        parts += ["--taker-root", str(taker_root)]
    if mm_root is not None:
        parts += ["--mm-root", str(mm_root)]
    if backtest_root is not None:
        parts += ["--backtest-root", str(backtest_root)]
    if labels_csv is not None:
        parts += ["--labels-csv", str(labels_csv)]
    return " ".join(_quote_part(part) for part in parts)


def _quote_part(value: Any) -> str:
    text = str(value)
    if not text or any(char.isspace() for char in text):
        return '"' + text.replace('"', '\\"') + '"'
    return text


def build_scoring_liveness(
    *,
    artifact_name: str,
    labels_csv: str | Path,
    quality_grades: Any = DEFAULT_QUALITY_GRADES,
    include_promotion_countable_labels: bool = True,
    last_scored_target_date: Any = None,
    rerun_command: str | None = None,
) -> dict[str, Any]:
    label_summary = latest_settled_label_summary(
        labels_csv,
        quality_grades=quality_grades,
        include_promotion_countable_labels=include_promotion_countable_labels,
    )
    latest = label_summary.get("latest_settled_label_date")
    last_scored = date_text(last_scored_target_date)
    blockers = []
    if latest and not last_scored:
        blockers.append({
            "gate": LIVENESS_BLOCKER_GATE,
            "detail": (
                f"{artifact_name} has no last_scored_target_date; "
                f"latest settled label is {latest}"
            ),
            "remediation_command": rerun_command,
        })
    elif latest and last_scored < latest:
        blockers.append({
            "gate": LIVENESS_BLOCKER_GATE,
            "detail": (
                f"{artifact_name} last_scored_target_date={last_scored} is older than "
                f"latest settled label {latest}"
            ),
            "remediation_command": rerun_command,
        })
    return {
        "status": "BLOCK" if blockers else ("PASS" if latest else "UNKNOWN"),
        "artifact_name": artifact_name,
        "last_scored_target_date": last_scored,
        "latest_settled_label_date": latest,
        "latest_label_count": label_summary.get("latest_label_count"),
        "selected_label_count": label_summary.get("selected_label_count"),
        "quality_grades": label_summary.get("quality_grades") or [],
        "include_promotion_countable_labels": label_summary.get("include_promotion_countable_labels"),
        "labels_csv": label_summary.get("labels_csv"),
        "labels_csv_exists": label_summary.get("labels_csv_exists"),
        "quality_counts": label_summary.get("quality_counts") or {},
        "selected_quality_counts": label_summary.get("selected_quality_counts") or {},
        "selected_promotion_countable_label_count": (
            label_summary.get("selected_promotion_countable_label_count") or 0
        ),
        "selected_promotion_countable_reasons": (
            label_summary.get("selected_promotion_countable_reasons") or {}
        ),
        "blocker_count": len(blockers),
        "first_blocker": blockers[0] if blockers else {},
        "blockers": blockers,
        "remediation_command": rerun_command,
    }


def liveness_blocker(liveness: dict[str, Any]) -> dict[str, Any]:
    first = (liveness or {}).get("first_blocker") or {}
    return {
        "gate": LIVENESS_BLOCKER_GATE,
        "detail": first.get("detail") or "model scoring liveness is stale",
        "remediation_command": first.get("remediation_command") or (liveness or {}).get("remediation_command"),
        "last_scored_target_date": (liveness or {}).get("last_scored_target_date"),
        "latest_settled_label_date": (liveness or {}).get("latest_settled_label_date"),
        "artifact_name": (liveness or {}).get("artifact_name"),
    }


def gate_has_liveness_blocker(gate: dict[str, Any] | None) -> bool:
    blockers = list((gate or {}).get("blockers") or [])
    first = (gate or {}).get("first_blocker") or {}
    if first:
        blockers.append(first)
    return any(
        row.get("gate") == LIVENESS_BLOCKER_GATE
        or row.get("category") == LIVENESS_BLOCKER_GATE
        for row in blockers
        if isinstance(row, dict)
    )


def apply_liveness_to_gate(gate: dict[str, Any] | None, liveness: dict[str, Any]) -> dict[str, Any]:
    gate = dict(gate or {})
    if (liveness or {}).get("status") != "BLOCK":
        return gate
    blocker = liveness_blocker(liveness)
    blockers = [
        row for row in (gate.get("blockers") or [])
        if isinstance(row, dict) and row.get("gate") != LIVENESS_BLOCKER_GATE
    ]
    blockers.insert(0, blocker)
    gate["status"] = "BLOCK"
    gate["blockers"] = blockers
    gate["blocker_count"] = len(blockers)
    gate["first_blocker"] = blockers[0] if blockers else {}
    gate["scoring_liveness"] = liveness
    return gate


def attach_scoring_liveness(
    payload: dict[str, Any],
    *,
    artifact_name: str,
    labels_csv: str | Path,
    quality_grades: Any = DEFAULT_QUALITY_GRADES,
    include_promotion_countable_labels: bool = True,
    last_scored_target_date: Any = None,
    rerun_command: str | None = None,
    gate_keys: tuple[str, ...] = (),
) -> dict[str, Any]:
    last_scored = date_text(last_scored_target_date) or last_scored_target_date_from_payload(payload)
    liveness = build_scoring_liveness(
        artifact_name=artifact_name,
        labels_csv=labels_csv,
        quality_grades=quality_grades,
        include_promotion_countable_labels=include_promotion_countable_labels,
        last_scored_target_date=last_scored,
        rerun_command=rerun_command,
    )
    payload["last_scored_target_date"] = liveness.get("last_scored_target_date")
    payload["latest_settled_label_date"] = liveness.get("latest_settled_label_date")
    payload["scoring_liveness"] = liveness
    for key in gate_keys:
        payload[key] = apply_liveness_to_gate(payload.get(key), liveness)
    return payload
