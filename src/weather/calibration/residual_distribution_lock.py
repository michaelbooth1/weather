"""Append-only pre-selection locks for ResidualDistributionV1 experiments.

The lock is deliberately a separate operation from training.  A training
process may consume a matching entry, but it cannot create one and claim that
the candidate/window was fixed before inspection.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from weather.experiment_contract import canonical_json, finalize_self_hash


LOCK_SCHEMA_VERSION = "residual_distribution_preselection_lock_v1"
DEFAULT_PRIMARY_METRICS = ("categorical_brier", "categorical_log_loss")
DEFAULT_PROTECTED_METRICS = (
    "rps",
    "ece",
    "sharpness",
    "winner_rank",
    "per_market_brier",
)
DEFAULT_COMPARATORS = (
    "frozen_current_release",
    "climatology",
    "item50",
    "dynamic_source",
)


class PreselectionLockError(ValueError):
    """A pre-selection lock is malformed, mutable, or does not match a run."""


def _iso_utc(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise PreselectionLockError("created_at_utc must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise PreselectionLockError("created_at_utc must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _dates(values: Sequence[str]) -> list[str]:
    output = sorted({str(value).strip() for value in values if str(value).strip()})
    if not output:
        raise PreselectionLockError("at least one locked target date is required")
    for value in output:
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise PreselectionLockError(f"invalid locked target date: {value!r}") from exc
    return output


def _sha256(value: Any, field: str, *, optional: bool = False) -> str | None:
    text = str(value or "").strip().lower()
    if optional and not text:
        return None
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise PreselectionLockError(f"{field} must be a SHA-256 hex digest")
    return text


def build_preselection_lock(
    *,
    candidate_id: str,
    corpus_sha256: str,
    locked_dates: Sequence[str],
    corpus_manifest_sha256: str | None = None,
    expected_market_ids: Sequence[str],
    expected_cutoff_hours: Sequence[int],
    primary_metrics: Sequence[str] = DEFAULT_PRIMARY_METRICS,
    protected_metrics: Sequence[str] = DEFAULT_PROTECTED_METRICS,
    comparators: Sequence[str] = DEFAULT_COMPARATORS,
    embargo_days: int = 3,
    minimum_outer_dates: int = 14,
    minimum_locked_dates: int = 14,
    created_at_utc: str | None = None,
) -> dict[str, Any]:
    """Build a self-hashed declaration that can be appended before training."""

    candidate = str(candidate_id or "").strip()
    if not candidate:
        raise PreselectionLockError("candidate_id is required")
    markets = sorted({str(value).strip() for value in expected_market_ids if str(value).strip()})
    cutoffs = sorted({int(value) for value in expected_cutoff_hours})
    if not markets:
        raise PreselectionLockError("expected_market_ids cannot be empty")
    if not cutoffs or any(value not in range(24) for value in cutoffs):
        raise PreselectionLockError("expected_cutoff_hours must be unique hours from 0 through 23")
    primary = list(dict.fromkeys(str(value).strip() for value in primary_metrics if str(value).strip()))
    protected = list(dict.fromkeys(str(value).strip() for value in protected_metrics if str(value).strip()))
    required_comparators = list(dict.fromkeys(str(value).strip() for value in comparators if str(value).strip()))
    if not primary or not protected or not required_comparators:
        raise PreselectionLockError("metrics and comparators must be predeclared")
    if int(embargo_days) not in range(3, 8):
        raise PreselectionLockError("embargo_days must be between 3 and 7")
    if int(minimum_outer_dates) < 14 or int(minimum_locked_dates) < 14:
        raise PreselectionLockError("outer and locked windows must each require at least 14 dates")
    return finalize_self_hash(
        {
            "schema_version": LOCK_SCHEMA_VERSION,
            "artifact_type": "residual_distribution_preselection_lock",
            "created_at_utc": _iso_utc(created_at_utc),
            "candidate_id": candidate,
            "corpus_sha256": _sha256(corpus_sha256, "corpus_sha256"),
            "corpus_manifest_sha256": _sha256(
                corpus_manifest_sha256,
                "corpus_manifest_sha256",
                optional=True,
            ),
            "locked_dates": _dates(locked_dates),
            "expected_market_ids": markets,
            "expected_cutoff_hours": cutoffs,
            "primary_metrics": primary,
            "protected_metrics": protected,
            "comparators": required_comparators,
            "embargo_days": int(embargo_days),
            "minimum_outer_dates": int(minimum_outer_dates),
            "minimum_locked_dates": int(minimum_locked_dates),
            "selection_unit": "whole_fleet_target_date",
            "cluster_unit": "whole_fleet_target_date",
        },
        hash_field="lock_sha256",
    )


def verify_preselection_lock(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != LOCK_SCHEMA_VERSION:
        raise PreselectionLockError("unsupported pre-selection lock schema")
    expected = finalize_self_hash(
        {key: value for key, value in payload.items() if key != "lock_sha256"},
        hash_field="lock_sha256",
    )
    if payload.get("lock_sha256") != expected.get("lock_sha256"):
        raise PreselectionLockError("pre-selection lock self-hash mismatch")
    # Rebuild to enforce normalized fields and semantic minima.
    normalized = build_preselection_lock(
        candidate_id=str(payload.get("candidate_id") or ""),
        corpus_sha256=str(payload.get("corpus_sha256") or ""),
        corpus_manifest_sha256=payload.get("corpus_manifest_sha256"),
        locked_dates=list(payload.get("locked_dates") or []),
        expected_market_ids=list(payload.get("expected_market_ids") or []),
        expected_cutoff_hours=list(payload.get("expected_cutoff_hours") or []),
        primary_metrics=list(payload.get("primary_metrics") or []),
        protected_metrics=list(payload.get("protected_metrics") or []),
        comparators=list(payload.get("comparators") or []),
        embargo_days=int(payload.get("embargo_days") or 0),
        minimum_outer_dates=int(payload.get("minimum_outer_dates") or 0),
        minimum_locked_dates=int(payload.get("minimum_locked_dates") or 0),
        created_at_utc=str(payload.get("created_at_utc") or ""),
    )
    if canonical_json(normalized) != canonical_json(dict(payload)):
        raise PreselectionLockError("pre-selection lock is not canonical")
    return normalized


def read_preselection_lock_ledger(path: str | Path) -> list[dict[str, Any]]:
    ledger = Path(path)
    if not ledger.exists():
        return []
    rows: list[dict[str, Any]] = []
    with ledger.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise PreselectionLockError(
                    f"{ledger}:{line_number} contains invalid JSON"
                ) from exc
            if not isinstance(payload, Mapping):
                raise PreselectionLockError(f"{ledger}:{line_number} must be an object")
            rows.append(verify_preselection_lock(payload))
    hashes = [row["lock_sha256"] for row in rows]
    if len(hashes) != len(set(hashes)):
        raise PreselectionLockError("pre-selection lock ledger contains duplicate entries")
    return rows


def append_preselection_lock(path: str | Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Append one durable entry; existing bytes are never rewritten."""

    row = verify_preselection_lock(payload)
    ledger = Path(path)
    existing = read_preselection_lock_ledger(ledger)
    if any(item["candidate_id"] == row["candidate_id"] for item in existing):
        raise PreselectionLockError(
            f"candidate_id {row['candidate_id']!r} is already registered"
        )
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical_json(row) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return row


def find_matching_preselection_lock(
    rows: Sequence[Mapping[str, Any]],
    *,
    candidate_id: str,
    corpus_sha256: str,
    locked_dates: Sequence[str],
    evaluation_generated_at_utc: str | None = None,
) -> dict[str, Any] | None:
    expected_dates = _dates(locked_dates)
    expected_hash = _sha256(corpus_sha256, "corpus_sha256")
    matches = [
        verify_preselection_lock(row)
        for row in rows
        if str(row.get("candidate_id") or "") == str(candidate_id)
        and str(row.get("corpus_sha256") or "").lower() == expected_hash
        and list(row.get("locked_dates") or []) == expected_dates
    ]
    if len(matches) > 1:
        raise PreselectionLockError("multiple pre-selection locks match one candidate run")
    if not matches:
        return None
    match = matches[0]
    if evaluation_generated_at_utc:
        locked_at = datetime.fromisoformat(match["created_at_utc"])
        evaluated_at = datetime.fromisoformat(str(evaluation_generated_at_utc).replace("Z", "+00:00"))
        if locked_at >= evaluated_at:
            raise PreselectionLockError("pre-selection lock was not recorded before evaluation")
    return match


def _csv_strings(value: str) -> tuple[str, ...]:
    values = tuple(dict.fromkeys(item.strip() for item in str(value).split(",") if item.strip()))
    if not values:
        raise argparse.ArgumentTypeError("at least one comma-separated value is required")
    return values


def _csv_hours(value: str) -> tuple[int, ...]:
    try:
        hours = tuple(dict.fromkeys(int(item.strip()) for item in str(value).split(",") if item.strip()))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("cutoff hours must be integers") from exc
    if not hours or any(hour not in range(24) for hour in hours):
        raise argparse.ArgumentTypeError("cutoff hours must be between 0 and 23")
    return hours


def _dates_file(path: str | Path) -> list[str]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, Mapping):
        payload = payload.get("target_dates") or payload.get("locked_dates")
    if not isinstance(payload, list):
        raise PreselectionLockError("locked dates file must contain a JSON list")
    return [str(value) for value in payload]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Append a ResidualDistributionV1 pre-selection lock before evaluation."
    )
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--corpus-sha256", required=True)
    parser.add_argument("--corpus-manifest-sha256", required=True)
    parser.add_argument("--locked-dates-file", required=True)
    parser.add_argument("--expected-market-ids", type=_csv_strings, required=True)
    parser.add_argument("--expected-cutoff-hours", type=_csv_hours, required=True)
    parser.add_argument("--comparators", type=_csv_strings, default=DEFAULT_COMPARATORS)
    parser.add_argument("--embargo-days", type=int, choices=range(3, 8), default=3)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    row = build_preselection_lock(
        candidate_id=args.candidate_id,
        corpus_sha256=args.corpus_sha256,
        corpus_manifest_sha256=args.corpus_manifest_sha256,
        locked_dates=_dates_file(args.locked_dates_file),
        expected_market_ids=args.expected_market_ids,
        expected_cutoff_hours=args.expected_cutoff_hours,
        comparators=args.comparators,
        embargo_days=args.embargo_days,
    )
    appended = append_preselection_lock(args.ledger, row)
    print(
        f"ResidualDistributionV1 lock: candidate={appended['candidate_id']} "
        f"dates={len(appended['locked_dates'])} sha256={appended['lock_sha256']}"
    )


__all__ = [name for name in globals() if not name.startswith("_")]


if __name__ == "__main__":
    main()
