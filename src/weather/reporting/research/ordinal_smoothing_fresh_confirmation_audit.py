"""Read-only feasibility audit for a fresh ordinal-smoothing confirmation panel.

The H1 tune and holdout remain sealed.  This command examines only a later,
explicit date interval, builds a new scratch promotion-corpus manifest, verifies
every tape/replay hash immediately, and asks whether each date has an exact
12-market panel with daily-summary settlement and replay records produced by
the current distribution code/artifact identity.

It reads no H1 holdout cache, selects no parameter, scores no outcome, and
authorizes no serving or promotion action.  A memory-bounded W0 replay of the
captured source records supplies a separate counterfactual-current-code
feasibility tier; the strict recorded-current identity tier is never relaxed.
Runtime/storage projections are planning estimates supplied from already-
observed arm costs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from weather.backtesting.replay import (
    distribution_l1,
    index_records_by_snapshot,
    load_replay_records,
    replay_distribution,
    replay_model_identity,
)
from weather.backtesting.settled_days import discover_settled_folders, folder_market_id
from weather.market.market_config import date_from_event_slug
from weather.market.market_registry import REGISTRY
from weather.model.model_identity import identity_hash, model_replay_identity
from weather.reporting.formatting import fmt_num, markdown_table
from weather.reporting.promotion.promotion_corpus import (
    DEFAULT_QUALITY_GRADES,
    build_promotion_corpus,
    verify_entry_inputs,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("ordinal_smoothing_fresh_confirmation_audit")
MAX_DATE_SPAN_DAYS = 62
DEFAULT_SIGMAS = (0.5, 0.75, 1.0, 1.5)
DEFAULT_WEIGHTS = (0.1, 0.25, 0.5, 0.75, 1.0)
FIDELITY_FAITHFUL_L1 = 0.01
MASS_TOLERANCE = 1e-8
IDENTITY_CORE_FIELDS = (
    "schema_version",
    "model_version",
    "market_id",
    "active_model_kind",
    "code_hash",
    "artifact_hash",
)


class FreshConfirmationAuditError(ValueError):
    """Raised when a path, date, or planning contract is unsafe or ambiguous."""


@dataclass(frozen=True)
class PlanningInputs:
    existing_sigma: float
    sigmas: tuple[float, ...]
    weights: tuple[float, ...]
    tune_arm_minutes: float
    tune_cache_bytes: int
    reference_holdout_dates: int
    holdout_arm_minutes: float
    holdout_cache_bytes: int
    old_tune_dates: int


def _resolved(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_stable(path: Path) -> str:
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise FreshConfirmationAuditError(f"file changed while hashing: {path}")
    return digest.hexdigest()


def _parse_date(value: str, field: str) -> date:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError as exc:
        raise FreshConfirmationAuditError(
            f"{field} must be an ISO date, got {value!r}"
        ) from exc


def _date_range(start: date, end: date) -> tuple[str, ...]:
    if end < start:
        raise FreshConfirmationAuditError("end date precedes start date")
    days = (end - start).days + 1
    if days > MAX_DATE_SPAN_DAYS:
        raise FreshConfirmationAuditError(
            f"audit interval exceeds {MAX_DATE_SPAN_DAYS} days"
        )
    return tuple((start + timedelta(days=offset)).isoformat() for offset in range(days))


def _parse_positive_grid(value: str, field: str) -> tuple[float, ...]:
    try:
        values = tuple(float(item.strip()) for item in str(value).split(",") if item.strip())
    except ValueError as exc:
        raise FreshConfirmationAuditError(f"{field} contains a nonnumeric value") from exc
    if not values or any(item <= 0.0 for item in values):
        raise FreshConfirmationAuditError(f"{field} must contain positive values")
    if len(values) != len(set(values)) or tuple(sorted(values)) != values:
        raise FreshConfirmationAuditError(f"{field} must be unique and sorted")
    return values


def _daily_summary_source(value: Any) -> bool:
    source = str(value or "").strip().lower()
    return source == "daily_summary" or source.endswith(":daily_summary")


def validate_paths(
    snapshots_root: str | Path,
    manifest_out: str | Path,
    json_out: str | Path,
    report_out: str | Path,
) -> dict[str, Path]:
    paths = {
        "snapshots_root": _resolved(snapshots_root),
        "manifest_out": _resolved(manifest_out),
        "json_out": _resolved(json_out),
        "report_out": _resolved(report_out),
    }
    if not paths["snapshots_root"].is_dir():
        raise FreshConfirmationAuditError(
            f"snapshot root is missing: {paths['snapshots_root']}"
        )
    outputs = [paths["manifest_out"], paths["json_out"], paths["report_out"]]
    if len({os.path.normcase(str(path)) for path in outputs}) != len(outputs):
        raise FreshConfirmationAuditError("output paths must be distinct")
    for output in outputs:
        if _is_within(output, paths["snapshots_root"].parent):
            raise FreshConfirmationAuditError(
                f"output aliases the read-only input data tree: {output}"
            )
        if output.exists():
            raise FreshConfirmationAuditError(
                f"refusing to overwrite existing audit output: {output}"
            )
    return paths


def discover_interval_folders(
    snapshots_root: Path, *, start: date, end: date, as_of: date
) -> tuple[list[Path], dict[str, Any]]:
    if as_of <= end:
        raise FreshConfirmationAuditError(
            "as-of date must be later than the last confirmation target date"
        )
    all_settled = discover_settled_folders(
        snapshots_root, as_of=as_of, required_file="snapshots_long.csv"
    )
    selected: list[Path] = []
    by_pair: dict[tuple[str, str], list[str]] = defaultdict(list)
    for folder in all_settled:
        target = date_from_event_slug(folder.name)
        market_id = folder_market_id(folder)
        if target is None or market_id is None or not (start <= target <= end):
            continue
        selected.append(folder)
        by_pair[(target.isoformat(), market_id)].append(folder.name)
    duplicate_pairs = {
        f"{target}/{market_id}": names
        for (target, market_id), names in sorted(by_pair.items())
        if len(names) != 1
    }
    return selected, {
        "settled_folders_in_interval": len(selected),
        "unique_market_dates": len(by_pair),
        "duplicate_market_date_folders": duplicate_pairs,
    }


def _current_identity_for_active_kind(
    market_id: str,
    active_model_kind: str,
    cache: dict[tuple[str, str], Mapping[str, Any]],
) -> Mapping[str, Any]:
    key = (market_id, active_model_kind)
    if key not in cache:
        # Lazy import keeps the read-only audit cheap during module/test import.
        from weather.model.toronto_model import TorontoHighTempModel

        model = TorontoHighTempModel(market_id=market_id)
        model.active_model_kind = active_model_kind
        cache[key] = model_replay_identity(model)
    return cache[key]


def audit_manifest_entries(
    manifest: Mapping[str, Any],
    *,
    snapshots_root: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    current_identity_cache: dict[tuple[str, str], Mapping[str, Any]] = {}
    identity_differences: dict[tuple[Any, ...], dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    total_warnings: list[str] = []
    for entry in sorted(
        manifest.get("entries") or [],
        key=lambda item: (str(item.get("target_date")), str(item.get("market_id"))),
    ):
        folder = snapshots_root / str(entry.get("folder_name") or entry.get("event_slug") or "")
        tape = folder / "snapshots_long.csv"
        frame = pd.read_csv(tape)
        records = index_records_by_snapshot(load_replay_records(folder))
        warnings = verify_entry_inputs(entry, folder, frame, records)
        total_warnings.extend(warnings)
        pinned_ids = tuple(str(value) for value in entry.get("snapshot_ids") or [])
        identities_present = 0
        exact_current = 0
        missing_active_kind = 0
        recorded_identity_hashes: Counter[str] = Counter()
        current_identity_hashes: Counter[str] = Counter()
        for snapshot_id in pinned_ids:
            record = records.get(snapshot_id) or {}
            recorded = record.get("model_identity") or {}
            recorded_hash = identity_hash(recorded)
            active_kind = str(recorded.get("active_model_kind") or "")
            if recorded_hash:
                identities_present += 1
                recorded_identity_hashes[str(recorded_hash)] += 1
            if not active_kind:
                missing_active_kind += 1
                continue
            current = _current_identity_for_active_kind(
                str(entry.get("market_id") or ""),
                active_kind,
                current_identity_cache,
            )
            current_hash = identity_hash(current)
            if current_hash:
                current_identity_hashes[str(current_hash)] += 1
            if recorded_hash and recorded_hash == current_hash:
                exact_current += 1
            elif recorded_hash and current_hash:
                changed_fields = tuple(
                    field
                    for field in IDENTITY_CORE_FIELDS
                    if recorded.get(field) != current.get(field)
                )
                difference_key = (
                    str(entry.get("market_id") or ""),
                    active_kind,
                    str(recorded_hash),
                    str(current_hash),
                    changed_fields,
                )
                if difference_key not in identity_differences:
                    identity_differences[difference_key] = {
                        "market_id": str(entry.get("market_id") or ""),
                        "active_model_kind": active_kind,
                        "recorded_identity_hash": str(recorded_hash),
                        "current_identity_hash": str(current_hash),
                        "changed_fields": list(changed_fields),
                        "recorded": {
                            field: recorded.get(field) for field in IDENTITY_CORE_FIELDS
                        },
                        "current": {
                            field: current.get(field) for field in IDENTITY_CORE_FIELDS
                        },
                        "snapshots": 0,
                        "target_dates": set(),
                    }
                identity_differences[difference_key]["snapshots"] += 1
                identity_differences[difference_key]["target_dates"].add(
                    str(entry.get("target_date") or "")
                )
        snapshot_count = len(pinned_ids)
        tape_hashes = entry.get("tape_row_hashes") or {}
        replay_hashes = entry.get("replay_record_hashes") or {}
        pin_complete = bool(snapshot_count) and (
            len(tape_hashes) == snapshot_count
            and len(replay_hashes) == snapshot_count
            and bool(entry.get("label_hash"))
            and not warnings
        )
        identity_complete = bool(snapshot_count) and identities_present == snapshot_count
        exact_current_complete = bool(snapshot_count) and exact_current == snapshot_count
        row = {
            "event_slug": entry.get("event_slug"),
            "market_id": entry.get("market_id"),
            "target_date": entry.get("target_date"),
            "settlement_source": entry.get("settlement_source"),
            "settlement_bucket_present": entry.get("settlement_bucket") is not None,
            "daily_summary_settlement": _daily_summary_source(entry.get("settlement_source")),
            "quality_grade": entry.get("quality_grade"),
            "admitted_by": entry.get("admitted_by"),
            "snapshot_count": snapshot_count,
            "snapshot_count_in_tape": int(entry.get("snapshot_count_in_tape") or 0),
            "replay_record_count": int(entry.get("replay_record_count") or 0),
            "identity_record_count": identities_present,
            "exact_current_identity_count": exact_current,
            "missing_active_model_kind_count": missing_active_kind,
            "pin_complete": pin_complete,
            "identity_complete": identity_complete,
            "exact_current_identity_complete": exact_current_complete,
            "verification_warnings": warnings,
            "recorded_identity_hashes": dict(sorted(recorded_identity_hashes.items())),
            "current_identity_hashes": dict(sorted(current_identity_hashes.items())),
        }
        rows.append(row)
    return rows, {
        "entries_verified": len(rows),
        "verification_warning_count": len(total_warnings),
        "verification_warnings": total_warnings,
        "current_identity_variants": [
            {
                "market_id": market_id,
                "active_model_kind": active_kind,
                "identity_hash": identity_hash(identity),
                "model_version": identity.get("model_version"),
                "code_hash": identity.get("code_hash"),
                "artifact_hash": identity.get("artifact_hash"),
            }
            for (market_id, active_kind), identity in sorted(current_identity_cache.items())
        ],
        "recorded_current_identity_differences": [
            {
                **difference,
                "target_dates": sorted(difference["target_dates"]),
            }
            for difference in sorted(
                identity_differences.values(),
                key=lambda item: (
                    item["market_id"],
                    item["active_model_kind"],
                    item["recorded_identity_hash"],
                ),
            )
        ],
    }


def build_date_panel(
    expected_dates: Sequence[str], rows: Iterable[Mapping[str, Any]]
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    expected_markets = set(REGISTRY)
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("target_date") or "")].append(row)
    panel: list[dict[str, Any]] = []
    strict_eligible: list[str] = []
    counterfactual_structural: list[str] = []
    for target_date in expected_dates:
        date_rows = grouped.get(target_date, [])
        markets = {str(row.get("market_id") or "") for row in date_rows}
        exact_market_panel = markets == expected_markets and len(date_rows) == len(expected_markets)
        pin_complete = exact_market_panel and all(bool(row.get("pin_complete")) for row in date_rows)
        settlement_complete = exact_market_panel and all(
            bool(row.get("settlement_bucket_present")) for row in date_rows
        )
        daily_summary_complete = exact_market_panel and all(
            bool(row.get("daily_summary_settlement")) for row in date_rows
        )
        identity_complete = exact_market_panel and all(
            bool(row.get("identity_complete")) for row in date_rows
        )
        exact_current_identity = exact_market_panel and all(
            bool(row.get("exact_current_identity_complete")) for row in date_rows
        )
        counterfactual_structure_eligible = all(
            (
                exact_market_panel,
                pin_complete,
                settlement_complete,
                daily_summary_complete,
            )
        )
        strict_confirmation_eligible = all(
            (
                counterfactual_structure_eligible,
                identity_complete,
                exact_current_identity,
            )
        )
        if counterfactual_structure_eligible:
            counterfactual_structural.append(target_date)
        if strict_confirmation_eligible:
            strict_eligible.append(target_date)
        panel.append(
            {
                "target_date": target_date,
                "market_count": len(markets),
                "missing_markets": sorted(expected_markets - markets),
                "extra_markets": sorted(markets - expected_markets),
                "exact_12_market_panel": exact_market_panel,
                "pin_complete": pin_complete,
                "settlement_complete": settlement_complete,
                "daily_summary_settlement_complete": daily_summary_complete,
                "identity_complete": identity_complete,
                "exact_current_identity_complete": exact_current_identity,
                "counterfactual_structure_eligible": counterfactual_structure_eligible,
                "strict_confirmation_eligible": strict_confirmation_eligible,
            }
        )
    return panel, strict_eligible, counterfactual_structural


def _default_model_factory(market_id: str) -> Any:
    from weather.model.toronto_model import TorontoHighTempModel

    return TorontoHighTempModel(market_id=market_id)


def _default_record_loader(folder: Path) -> Mapping[str, Mapping[str, Any]]:
    return index_records_by_snapshot(load_replay_records(folder))


def _distribution_digest(distribution: Mapping[Any, Any]) -> tuple[str, float, bool]:
    normalized: dict[str, float] = {}
    valid = True
    for bucket, probability in distribution.items():
        try:
            key = str(int(bucket))
            value = float(probability)
        except (TypeError, ValueError):
            valid = False
            continue
        if not math.isfinite(value) or value < 0.0:
            valid = False
        normalized[key] = value
    mass = sum(normalized.values())
    digest = hashlib.sha256(_canonical_json(normalized).encode("utf-8")).hexdigest()
    return digest, mass, valid


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def run_w0_replay_gate(
    manifest: Mapping[str, Any],
    *,
    snapshots_root: Path,
    target_dates: Sequence[str],
    corpus_warning_count: int,
    record_loader: Any = None,
    model_factory: Any = None,
    replay_fn: Any = None,
    replay_identity_fn: Any = None,
) -> dict[str, Any]:
    """Replay captured sources without bands/outcomes for Tier-2 feasibility.

    Only compact counters, identity cohorts, and one fleet-date of distribution
    hashes are retained.  This is the W0 replay/corpus/fidelity gate, not a
    candidate experiment and not a fresh settlement score.
    """

    started = time.perf_counter()
    dates = tuple(str(value) for value in target_dates)
    wanted_dates = set(dates)
    entries = [
        entry
        for entry in manifest.get("entries") or []
        if str(entry.get("target_date") or "") in wanted_dates
    ]
    load_records = record_loader or _default_record_loader
    make_model = model_factory or _default_model_factory
    replay = replay_fn or replay_distribution
    replay_identity = replay_identity_fn or replay_model_identity
    expected_snapshots = sum(len(entry.get("snapshot_ids") or []) for entry in entries)
    per_date: dict[str, dict[str, Any]] = {
        target_date: {
            "target_date": target_date,
            "market_days": 0,
            "expected_snapshots": 0,
            "replayed_snapshots": 0,
            "replay_failures": 0,
            "mass_failures": 0,
            "missing_recorded_distributions": 0,
        }
        for target_date in dates
    }
    for entry in entries:
        stats = per_date[str(entry.get("target_date") or "")]
        stats["market_days"] += 1
        stats["expected_snapshots"] += len(entry.get("snapshot_ids") or [])

    errors: list[dict[str, Any]] = []
    replay_failures = 0
    mass_failures = 0
    missing_recorded_distributions = 0
    replayed_snapshots = 0
    same_identity_l1: list[float] = []
    changed_identity_l1: list[float] = []
    legacy_same_label_l1: list[float] = []
    identity_transitions: dict[tuple[Any, ...], dict[str, Any]] = {}
    canary_date = dates[0] if dates else None
    canary_first: dict[tuple[str, str], str] = {}
    models: dict[str, Any] = {}

    def model_for(market_id: str, pool: dict[str, Any]) -> Any:
        if market_id not in pool:
            pool[market_id] = make_model(market_id)
        return pool[market_id]

    def append_error(
        *, target_date: str, market_id: str, snapshot_id: str, reason: str
    ) -> None:
        if len(errors) < 100:
            errors.append(
                {
                    "target_date": target_date,
                    "market_id": market_id,
                    "snapshot_id": snapshot_id,
                    "reason": reason,
                }
            )

    for entry in sorted(
        entries,
        key=lambda item: (str(item.get("target_date")), str(item.get("market_id"))),
    ):
        target_date = str(entry.get("target_date") or "")
        market_id = str(entry.get("market_id") or "")
        folder = snapshots_root / str(entry.get("folder_name") or entry.get("event_slug") or "")
        records = load_records(folder)
        model = model_for(market_id, models)
        for raw_snapshot_id in entry.get("snapshot_ids") or []:
            snapshot_id = str(raw_snapshot_id)
            record = records.get(snapshot_id)
            if not record:
                replay_failures += 1
                per_date[target_date]["replay_failures"] += 1
                append_error(
                    target_date=target_date,
                    market_id=market_id,
                    snapshot_id=snapshot_id,
                    reason="pinned replay record missing",
                )
                continue
            try:
                distribution = replay(model, record)
                if not distribution:
                    raise ValueError("current W0 replay returned no distribution")
                digest, mass, valid = _distribution_digest(distribution)
                if not valid or abs(mass - 1.0) > MASS_TOLERANCE:
                    mass_failures += 1
                    per_date[target_date]["mass_failures"] += 1
                    append_error(
                        target_date=target_date,
                        market_id=market_id,
                        snapshot_id=snapshot_id,
                        reason=f"invalid probability simplex mass={mass!r}",
                    )
                replayed = replay_identity(model) or {}
                recorded = record.get("model_identity") or {}
                recorded_hash = identity_hash(recorded)
                replayed_hash = identity_hash(replayed)
                recorded_distribution = record.get("recorded_distribution")
                if not recorded_distribution:
                    missing_recorded_distributions += 1
                    per_date[target_date]["missing_recorded_distributions"] += 1
                else:
                    l1 = float(distribution_l1(distribution, recorded_distribution))
                    if recorded_hash and recorded_hash == replayed_hash:
                        same_identity_l1.append(l1)
                    elif (
                        not recorded_hash
                        and record.get("model_version") == replayed.get("model_version")
                    ):
                        legacy_same_label_l1.append(l1)
                    else:
                        changed_identity_l1.append(l1)
                if recorded_hash != replayed_hash:
                    changed_fields = tuple(
                        field
                        for field in IDENTITY_CORE_FIELDS
                        if recorded.get(field) != replayed.get(field)
                    )
                    transition_key = (
                        market_id,
                        str(recorded_hash or "missing"),
                        str(replayed_hash or "missing"),
                        changed_fields,
                    )
                    if transition_key not in identity_transitions:
                        identity_transitions[transition_key] = {
                            "market_id": market_id,
                            "recorded_identity_hash": recorded_hash,
                            "replayed_identity_hash": replayed_hash,
                            "changed_fields": list(changed_fields),
                            "recorded": {
                                field: recorded.get(field) for field in IDENTITY_CORE_FIELDS
                            },
                            "replayed": {
                                field: replayed.get(field) for field in IDENTITY_CORE_FIELDS
                            },
                            "snapshots": 0,
                            "target_dates": set(),
                        }
                    identity_transitions[transition_key]["snapshots"] += 1
                    identity_transitions[transition_key]["target_dates"].add(target_date)
                if target_date == canary_date:
                    canary_first[(market_id, snapshot_id)] = digest
                replayed_snapshots += 1
                per_date[target_date]["replayed_snapshots"] += 1
            except Exception as exc:  # noqa: BLE001 - evidence records each failed input
                replay_failures += 1
                per_date[target_date]["replay_failures"] += 1
                append_error(
                    target_date=target_date,
                    market_id=market_id,
                    snapshot_id=snapshot_id,
                    reason=f"{type(exc).__name__}: {exc}",
                )

    # A fresh model pool makes this an independent repeat, not a comparison of
    # a mutable model object's cached output with itself.
    canary_second_count = 0
    canary_mismatches: list[dict[str, Any]] = []
    canary_models: dict[str, Any] = {}
    for entry in sorted(
        (
            entry
            for entry in entries
            if str(entry.get("target_date") or "") == canary_date
        ),
        key=lambda item: str(item.get("market_id")),
    ):
        market_id = str(entry.get("market_id") or "")
        folder = snapshots_root / str(entry.get("folder_name") or entry.get("event_slug") or "")
        records = load_records(folder)
        model = model_for(market_id, canary_models)
        for raw_snapshot_id in entry.get("snapshot_ids") or []:
            snapshot_id = str(raw_snapshot_id)
            record = records.get(snapshot_id)
            expected = canary_first.get((market_id, snapshot_id))
            try:
                distribution = replay(model, record) if record else {}
                actual, _, valid = _distribution_digest(distribution) if distribution else (None, 0.0, False)
            except Exception:  # noqa: BLE001 - mismatch detail is sufficient here
                actual, valid = None, False
            canary_second_count += 1
            if not valid or expected is None or actual != expected:
                if len(canary_mismatches) < 100:
                    canary_mismatches.append(
                        {
                            "market_id": market_id,
                            "snapshot_id": snapshot_id,
                            "first_sha256": expected,
                            "second_sha256": actual,
                        }
                    )

    same_mean = _mean(same_identity_l1)
    same_faithful = bool(
        same_identity_l1 and same_mean is not None and same_mean <= FIDELITY_FAITHFUL_L1
    )
    blockers = []
    if not dates or not entries:
        blockers.append("no structurally eligible market-dates were supplied to W0 replay")
    if int(corpus_warning_count) != 0:
        blockers.append(f"corpus verification reported {corpus_warning_count} warning(s)")
    if replayed_snapshots != expected_snapshots or replay_failures:
        blockers.append(
            f"not every pinned snapshot replayed ({replayed_snapshots}/{expected_snapshots}; failures={replay_failures})"
        )
    if mass_failures:
        blockers.append(f"{mass_failures} replay distribution(s) failed the simplex gate")
    if missing_recorded_distributions:
        blockers.append(
            f"{missing_recorded_distributions} pinned replay record(s) lack a recorded distribution"
        )
    if canary_second_count != len(canary_first) or canary_mismatches:
        blockers.append(
            "independent W0 repeat canary mismatch: "
            f"first={len(canary_first)}, second={canary_second_count}, mismatches={len(canary_mismatches)}"
        )
    if same_identity_l1 and not same_faithful:
        blockers.append(
            "exact-identity fidelity mean L1 exceeds "
            f"{FIDELITY_FAITHFUL_L1}: {same_mean}"
        )
    per_date_rows = []
    for target_date in dates:
        row = dict(per_date[target_date])
        row["status"] = (
            "PASS"
            if row["market_days"] == len(REGISTRY)
            and row["replayed_snapshots"] == row["expected_snapshots"]
            and row["replay_failures"] == 0
            and row["mass_failures"] == 0
            and row["missing_recorded_distributions"] == 0
            else "BLOCK"
        )
        per_date_rows.append(row)
    status = "PASS" if not blockers else "BLOCK"
    return {
        "status": status,
        "outcome_blind": True,
        "weight": 0.0,
        "ordinal_smoothing_enabled": False,
        "target_dates": list(dates),
        "market_days": len(entries),
        "expected_snapshots": expected_snapshots,
        "replayed_snapshots": replayed_snapshots,
        "replay_failures": replay_failures,
        "mass_tolerance": MASS_TOLERANCE,
        "mass_failures": mass_failures,
        "missing_recorded_distributions": missing_recorded_distributions,
        "corpus_warning_count": int(corpus_warning_count),
        "fidelity": {
            "threshold_mean_l1": FIDELITY_FAITHFUL_L1,
            "same_identity_n": len(same_identity_l1),
            "same_identity_mean_l1": same_mean,
            "same_identity_max_l1": max(same_identity_l1, default=None),
            "same_identity_faithful": same_faithful if same_identity_l1 else None,
            "same_identity_status": (
                "PASS"
                if same_faithful
                else "NO_EXACT_IDENTITY_CANARY"
                if not same_identity_l1
                else "BLOCK"
            ),
            "legacy_same_label_n": len(legacy_same_label_l1),
            "legacy_same_label_mean_l1": _mean(legacy_same_label_l1),
            "changed_identity_n": len(changed_identity_l1),
            "changed_identity_mean_l1": _mean(changed_identity_l1),
            "changed_identity_max_l1": max(changed_identity_l1, default=None),
        },
        "determinism_canary": {
            "target_date": canary_date,
            "first_replay_distributions": len(canary_first),
            "second_replay_distributions": canary_second_count,
            "mismatch_count": len(canary_mismatches),
            "mismatches": canary_mismatches,
        },
        "per_date": per_date_rows,
        "identity_transitions": [
            {
                **transition,
                "target_dates": sorted(transition["target_dates"]),
            }
            for transition in sorted(
                identity_transitions.values(),
                key=lambda item: (
                    item["market_id"],
                    str(item["recorded_identity_hash"]),
                    str(item["replayed_identity_hash"]),
                ),
            )
        ],
        "blockers": blockers,
        "errors": errors,
        "runtime_seconds": time.perf_counter() - started,
        "bounded_memory_contract": (
            "one captured record/distribution at a time plus one fleet-date of SHA-256 canary hashes"
        ),
    }


def build_cost_estimate(
    planning: PlanningInputs, *, confirmation_dates: int
) -> dict[str, Any]:
    total_factorial_candidates = len(planning.sigmas) * len(planning.weights)
    reusable_candidates = (
        len(planning.weights) if planning.existing_sigma in planning.sigmas else 0
    )
    best_case_new_tune_arms = total_factorial_candidates - reusable_candidates
    cold_start_tune_arms = 1 + total_factorial_candidates  # one shared W0
    scale = confirmation_dates / planning.reference_holdout_dates
    confirmation_arm_minutes = planning.holdout_arm_minutes * scale
    confirmation_arm_bytes = round(planning.holdout_cache_bytes * scale)
    confirmation_arms = 2  # frozen W0 plus one tune-selected candidate
    # A physically comparable follow-up cannot reuse a whole-fleet H1 arm:
    # H1's same numeric sigma means different Celsius bandwidths across C/F.
    preferred_sigma_new_arms = len(planning.sigmas)
    return {
        "inputs": {
            "old_development_tune_dates_only": planning.old_tune_dates,
            "fresh_confirmation_dates_planned": confirmation_dates,
            "shared_numeric_native_sigma_grid": list(planning.sigmas),
            "positive_weight_grid": list(planning.weights),
            "shared_weight_zero_arm": True,
            "existing_sigma": planning.existing_sigma,
            "measured_tune_arm_minutes": planning.tune_arm_minutes,
            "measured_tune_cache_bytes": planning.tune_cache_bytes,
            "reference_holdout_dates": planning.reference_holdout_dates,
            "measured_holdout_arm_minutes": planning.holdout_arm_minutes,
            "measured_holdout_cache_bytes": planning.holdout_cache_bytes,
        },
        "factorial_best_case_reuse": {
            "new_tune_arms": best_case_new_tune_arms,
            "estimated_tune_minutes": best_case_new_tune_arms * planning.tune_arm_minutes,
            "estimated_tune_cache_bytes": best_case_new_tune_arms * planning.tune_cache_bytes,
            "confirmation_arms": confirmation_arms,
            "estimated_confirmation_minutes": confirmation_arms * confirmation_arm_minutes,
            "estimated_confirmation_cache_bytes": confirmation_arms * confirmation_arm_bytes,
            "reuse_condition": (
                "existing W0 and existing-sigma tune caches must pass exact corpus, "
                "code-compatibility, fingerprint, and technical-gate validation"
            ),
        },
        "factorial_cold_start": {
            "tune_arms": cold_start_tune_arms,
            "estimated_tune_minutes": cold_start_tune_arms * planning.tune_arm_minutes,
            "estimated_tune_cache_bytes": cold_start_tune_arms * planning.tune_cache_bytes,
            "confirmation_arms": confirmation_arms,
            "estimated_confirmation_minutes": confirmation_arms * confirmation_arm_minutes,
            "estimated_confirmation_cache_bytes": confirmation_arms * confirmation_arm_bytes,
        },
        "preferred_one_variable_sigma_refinement_best_case": {
            "fixed_weight": 1.0,
            "new_tune_arms": preferred_sigma_new_arms,
            "estimated_tune_minutes": preferred_sigma_new_arms * planning.tune_arm_minutes,
            "estimated_tune_cache_bytes": preferred_sigma_new_arms * planning.tune_cache_bytes,
            "reason": (
                "preserves the workstation program's one-variable discipline; "
                "H1 tune selected the weight-grid ceiling, so sigma is the next isolated variable; "
                "all arms are new because a physical-bandwidth contract changes at least one family"
            ),
            "required_unit_contract": (
                "predeclare physical-C anchors with sigma_F = 1.8 * sigma_C, "
                "or separate explicitly labeled C/F grids; never call a shared native numeric sigma physically comparable"
            ),
        },
        "unit_semantics": {
            "h1_sigma_numeric": planning.existing_sigma,
            "toronto_bandwidth": f"{planning.existing_sigma} C",
            "f_market_bandwidth": f"{planning.existing_sigma} F",
            "f_market_bandwidth_c_equivalent": planning.existing_sigma / 1.8,
            "physical_bandwidth_ratio_c_to_f": 1.8,
            "interpretation": (
                "H1 is a valid equal-native-bucket treatment, not a common-physical-bandwidth treatment"
            ),
        },
        "selection_firewall": {
            "expanded_selection_inputs": "old development/tune dates only",
            "original_h1_holdout_opened_for_selection": False,
            "fresh_panel_opened_for_selection": False,
            "fresh_panel_role": "one fixed, preregistered confirmation only",
            "no_reselection_after_confirmation": True,
        },
    }


def _market_summary(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("market_id") or "")].append(row)
    result = []
    for market_id in sorted(REGISTRY):
        items = grouped.get(market_id, [])
        result.append(
            {
                "market_id": market_id,
                "market_days": len(items),
                "pinned_snapshots": sum(int(item.get("snapshot_count") or 0) for item in items),
                "pin_complete_market_days": sum(bool(item.get("pin_complete")) for item in items),
                "daily_summary_market_days": sum(
                    bool(item.get("daily_summary_settlement")) for item in items
                ),
                "exact_current_identity_market_days": sum(
                    bool(item.get("exact_current_identity_complete")) for item in items
                ),
                "exact_current_identity_snapshots": sum(
                    int(item.get("exact_current_identity_count") or 0) for item in items
                ),
            }
        )
    return result


def run_audit(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], dict[str, Path]]:
    paths = validate_paths(
        args.snapshots_root, args.manifest_out, args.json_out, args.report_out
    )
    start = _parse_date(args.start_date, "start date")
    end = _parse_date(args.end_date, "end date")
    as_of = _parse_date(args.as_of, "as-of date")
    expected_dates = _date_range(start, end)
    sigmas = _parse_positive_grid(args.sigma_grid, "sigma grid")
    weights = _parse_positive_grid(args.weight_grid, "weight grid")
    planning = PlanningInputs(
        existing_sigma=float(args.existing_sigma),
        sigmas=sigmas,
        weights=weights,
        tune_arm_minutes=float(args.measured_tune_arm_minutes),
        tune_cache_bytes=int(args.measured_tune_cache_bytes),
        reference_holdout_dates=int(args.reference_holdout_dates),
        holdout_arm_minutes=float(args.measured_holdout_arm_minutes),
        holdout_cache_bytes=int(args.measured_holdout_cache_bytes),
        old_tune_dates=int(args.old_tune_dates),
    )
    if (
        planning.existing_sigma <= 0
        or planning.tune_arm_minutes <= 0
        or planning.tune_cache_bytes <= 0
        or planning.reference_holdout_dates <= 0
        or planning.holdout_arm_minutes <= 0
        or planning.holdout_cache_bytes <= 0
        or planning.old_tune_dates <= 0
    ):
        raise FreshConfirmationAuditError("planning measurements must be positive")

    folders, discovery = discover_interval_folders(
        paths["snapshots_root"], start=start, end=end, as_of=as_of
    )
    if not folders:
        raise FreshConfirmationAuditError(
            "no settled registered snapshot folders were found in the requested interval"
        )
    manifest = build_promotion_corpus(
        folders=folders,
        snapshots_root=paths["snapshots_root"],
        as_of=as_of,
        quality_grades=DEFAULT_QUALITY_GRADES,
        include_reconstructed=False,
        allow_unsettled=False,
        min_snapshots=1,
        admit_promotion_countable=True,
    )
    entry_rows, verification = audit_manifest_entries(
        manifest, snapshots_root=paths["snapshots_root"]
    )
    panel, strict_structural, counterfactual_structural = build_date_panel(
        expected_dates, entry_rows
    )
    exact_panels = [row["target_date"] for row in panel if row["exact_12_market_panel"]]
    settled_panels = [row["target_date"] for row in panel if row["settlement_complete"]]
    daily_panels = [
        row["target_date"] for row in panel if row["daily_summary_settlement_complete"]
    ]
    pin_panels = [row["target_date"] for row in panel if row["pin_complete"]]
    identity_panels = [
        row["target_date"] for row in panel if row["exact_current_identity_complete"]
    ]
    w0_gate = run_w0_replay_gate(
        manifest,
        snapshots_root=paths["snapshots_root"],
        target_dates=counterfactual_structural,
        corpus_warning_count=int(verification["verification_warning_count"]),
    )
    w0_pass_dates = [
        row["target_date"]
        for row in w0_gate.get("per_date") or []
        if row.get("status") == "PASS"
    ]
    strict_eligible = (
        list(strict_structural)
        if w0_gate.get("status") == "PASS"
        and set(strict_structural) <= set(w0_pass_dates)
        else []
    )
    counterfactual_eligible = (
        list(counterfactual_structural)
        if w0_gate.get("status") == "PASS"
        and set(counterfactual_structural) <= set(w0_pass_dates)
        else []
    )
    shared_blockers = []
    if discovery["duplicate_market_date_folders"]:
        shared_blockers.append("duplicate market-date snapshot folders exist in the interval")
    if manifest.get("skipped"):
        shared_blockers.append(
            f"{len(manifest['skipped'])} discovered folders were not corpus-admissible"
        )
    if verification["verification_warning_count"]:
        shared_blockers.append(
            "one or more pinned files changed during immediate verification"
        )
    strict_blockers = list(shared_blockers)
    counterfactual_blockers = list(shared_blockers)
    if len(strict_structural) != len(expected_dates):
        strict_blockers.append(
            f"only {len(strict_structural)}/{len(expected_dates)} dates have exact recorded-current identity"
        )
    if len(counterfactual_structural) != len(expected_dates):
        counterfactual_blockers.append(
            f"only {len(counterfactual_structural)}/{len(expected_dates)} dates satisfy the Tier-2 structural contract"
        )
    if w0_gate.get("status") != "PASS":
        counterfactual_blockers.extend(
            f"W0 gate: {reason}" for reason in w0_gate.get("blockers") or []
        )
        strict_blockers.extend(
            f"W0 gate: {reason}" for reason in w0_gate.get("blockers") or []
        )
    if len(strict_eligible) == len(expected_dates) and not strict_blockers:
        feasibility = "TIER_1_STRICT_READY"
    elif (
        len(counterfactual_eligible) == len(expected_dates)
        and not counterfactual_blockers
    ):
        feasibility = "TIER_2_COUNTERFACTUAL_FEASIBLE_REVIEW_REQUIRED"
    else:
        feasibility = "NO_COMPLETE_FRESH_CONFIRMATION_PANEL"
    cost = build_cost_estimate(planning, confirmation_dates=len(expected_dates))
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "COMPLETE",
        "research_only": True,
        "promotion_authorized": False,
        "audit_disposition": feasibility,
        "technical_blockers": sorted(
            set(strict_blockers + counterfactual_blockers)
        ),
        "contract": {
            "date_interval": list(expected_dates),
            "as_of": as_of.isoformat(),
            "canonical_markets": sorted(REGISTRY),
            "required_market_count_per_date": len(REGISTRY),
            "requires_exact_tape_and_replay_hash_pins": True,
            "requires_settlement_bucket": True,
            "requires_daily_summary_settlement_source": True,
            "tier_1_requires_identity_on_every_pinned_replay_record": True,
            "tier_1_requires_exact_current_identity_hash": True,
            "current_identity_method": (
                "recompute the full model replay identity for each captured active_model_kind; "
                "compare identity_hash exactly before replay"
            ),
            "tier_2_contract": (
                "exact 12-market/hash-pinned/daily-summary panel plus a successful "
                "outcome-blind current-code W0 replay, simplex, fidelity, and determinism gate"
            ),
        },
        "inputs": {
            "snapshots_root": str(paths["snapshots_root"]),
            "opened_read_only": True,
        },
        "outputs": {
            "manifest_out": str(paths["manifest_out"]),
            "json_out": str(paths["json_out"]),
            "report_out": str(paths["report_out"]),
            "outside_snapshots_root": True,
            "outside_input_data_root": True,
        },
        "discovery": discovery,
        "manifest": {
            "schema_version": manifest.get("schema_version"),
            "corpus_hash": manifest.get("corpus_hash"),
            "summary": manifest.get("summary") or {},
            "skipped": manifest.get("skipped") or [],
        },
        "verification": verification,
        "date_panel": panel,
        "market_summary": _market_summary(entry_rows),
        "entry_audit": entry_rows,
        "w0_counterfactual_replay_gate": w0_gate,
        "eligibility": {
            "expected_dates": list(expected_dates),
            "exact_12_market_dates": exact_panels,
            "pin_complete_dates": pin_panels,
            "settlement_complete_dates": settled_panels,
            "daily_summary_settlement_complete_dates": daily_panels,
            "exact_current_identity_dates": identity_panels,
            "tier_1_strict_structural_dates": strict_structural,
            "tier_1_strict_confirmation_eligible_dates": strict_eligible,
            "tier_1_blockers": strict_blockers,
            "tier_2_counterfactual_structural_dates": counterfactual_structural,
            "tier_2_w0_pass_dates": w0_pass_dates,
            "tier_2_counterfactual_confirmation_eligible_dates": counterfactual_eligible,
            "tier_2_blockers": counterfactual_blockers,
        },
        "expanded_tune_feasibility": cost,
        "safety": {
            "model_replay_performed": True,
            "model_replay_scope": "outcome-blind W0 captured-source feasibility gate only",
            "outcome_scoring_performed": False,
            "parameter_selection_performed": False,
            "original_h1_holdout_opened": False,
            "serving_pointer_changed": False,
            "artifact_promoted": False,
            "live_trading": False,
            "input_data_written": False,
        },
    }
    return payload, manifest, paths


def render_report(payload: Mapping[str, Any]) -> str:
    eligibility = payload.get("eligibility") or {}
    w0 = payload.get("w0_counterfactual_replay_gate") or {}
    w0_by_date = {
        str(row.get("target_date")): row for row in w0.get("per_date") or []
    }
    identity_differences = (
        (payload.get("verification") or {}).get(
            "recorded_current_identity_differences"
        )
        or []
    )
    cost = payload.get("expanded_tune_feasibility") or {}
    best = cost.get("factorial_best_case_reuse") or {}
    cold = cost.get("factorial_cold_start") or {}
    preferred = cost.get("preferred_one_variable_sigma_refinement_best_case") or {}
    unit_semantics = cost.get("unit_semantics") or {}
    lines = [
        "# Fresh Ordinal-Smoothing Confirmation Feasibility Audit",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Audit disposition: `{payload.get('audit_disposition')}`",
        "Mode: read-only research planning plus an outcome-blind W0 captured-source replay gate; no outcome scoring, parameter selection, promotion, or live action.",
        "",
        "## Outcome",
        "",
        *markdown_table(
            ["Contract", "Dates"],
            [
                ["Expected", len(eligibility.get("expected_dates") or [])],
                ["Exact 12-market", len(eligibility.get("exact_12_market_dates") or [])],
                ["Hash-pin complete", len(eligibility.get("pin_complete_dates") or [])],
                ["Settlement complete", len(eligibility.get("settlement_complete_dates") or [])],
                ["Daily-summary settlement", len(eligibility.get("daily_summary_settlement_complete_dates") or [])],
                ["Exact current identity", len(eligibility.get("exact_current_identity_dates") or [])],
                ["Tier 1 strict eligible", len(eligibility.get("tier_1_strict_confirmation_eligible_dates") or [])],
                ["Tier 2 structural", len(eligibility.get("tier_2_counterfactual_structural_dates") or [])],
                ["Tier 2 W0-gated eligible", len(eligibility.get("tier_2_counterfactual_confirmation_eligible_dates") or [])],
            ],
        ),
        "",
        "Tier 1 requires exact recorded=current replay identity on every pinned snapshot. Tier 2 never changes that verdict: it separately asks whether the same exact 12-market, hash-pinned, daily-summary panel is replayable under current W0 with clean corpus, simplex, fidelity, and repeat-determinism gates.",
        "",
        "## Date Panel",
        "",
        *markdown_table(
            ["Date", "Markets", "12", "Pins", "Daily", "Identity", "Tier 1", "Tier 2 structure", "W0"],
            [
                [
                    row.get("target_date"),
                    row.get("market_count"),
                    row.get("exact_12_market_panel"),
                    row.get("pin_complete"),
                    row.get("daily_summary_settlement_complete"),
                    row.get("exact_current_identity_complete"),
                    row.get("strict_confirmation_eligible"),
                    row.get("counterfactual_structure_eligible"),
                    (w0_by_date.get(str(row.get("target_date"))) or {}).get("status", "NOT_RUN"),
                ]
                for row in payload.get("date_panel") or []
            ],
        ),
        "",
        "## Outcome-Blind W0 Replay Gate",
        "",
        *markdown_table(
            ["Field", "Value"],
            [
                ["Status", w0.get("status")],
                ["Target dates", len(w0.get("target_dates") or [])],
                ["Market-days", w0.get("market_days")],
                ["Snapshots replayed / expected", f"{w0.get('replayed_snapshots')}/{w0.get('expected_snapshots')}"],
                ["Replay failures", w0.get("replay_failures")],
                ["Simplex failures", w0.get("mass_failures")],
                ["Missing recorded distributions", w0.get("missing_recorded_distributions")],
                ["Exact-identity fidelity cohort", (w0.get("fidelity") or {}).get("same_identity_n")],
                ["Exact-identity mean L1", fmt_num((w0.get("fidelity") or {}).get("same_identity_mean_l1"))],
                ["Changed-identity fidelity cohort", (w0.get("fidelity") or {}).get("changed_identity_n")],
                ["Changed-identity mean L1", fmt_num((w0.get("fidelity") or {}).get("changed_identity_mean_l1"))],
                ["Repeat-canary mismatches", (w0.get("determinism_canary") or {}).get("mismatch_count")],
                ["Runtime seconds", fmt_num(w0.get("runtime_seconds"), 2)],
            ],
        ),
        "",
        "The W0 gate replays captured source dictionaries only. It does not read market-band outcomes or compute Brier/log-loss; changed-identity L1 is descriptive and cannot upgrade Tier 1.",
        "",
        "## Recorded vs Current Identity Differences",
        "",
        *markdown_table(
            ["Market", "Path", "Changed fields", "Snapshots", "Dates", "Recorded hash", "Current hash"],
            [
                [
                    row.get("market_id"),
                    row.get("active_model_kind"),
                    ", ".join(row.get("changed_fields") or []),
                    row.get("snapshots"),
                    len(row.get("target_dates") or []),
                    row.get("recorded_identity_hash"),
                    row.get("current_identity_hash"),
                ]
                for row in identity_differences
            ],
        ),
        "",
        "## Market Integrity",
        "",
        *markdown_table(
            ["Market", "Days", "Snapshots", "Pinned days", "Daily days", "Current-ID days", "Current-ID snapshots"],
            [
                [
                    row.get("market_id"),
                    row.get("market_days"),
                    row.get("pinned_snapshots"),
                    row.get("pin_complete_market_days"),
                    row.get("daily_summary_market_days"),
                    row.get("exact_current_identity_market_days"),
                    row.get("exact_current_identity_snapshots"),
                ]
                for row in payload.get("market_summary") or []
            ],
        ),
        "",
        "## Expanded Tune Cost Before Confirmation",
        "",
        *markdown_table(
            ["Plan", "Tune arms", "Tune hours", "Tune GiB", "Confirmation hours", "Confirmation GiB"],
            [
                [
                    "sigma x weight, validated cache reuse",
                    best.get("new_tune_arms"),
                    fmt_num(float(best.get("estimated_tune_minutes") or 0) / 60.0, 2),
                    fmt_num(float(best.get("estimated_tune_cache_bytes") or 0) / (1024 ** 3), 2),
                    fmt_num(float(best.get("estimated_confirmation_minutes") or 0) / 60.0, 2),
                    fmt_num(float(best.get("estimated_confirmation_cache_bytes") or 0) / (1024 ** 3), 2),
                ],
                [
                    "sigma x weight, cold start",
                    cold.get("tune_arms"),
                    fmt_num(float(cold.get("estimated_tune_minutes") or 0) / 60.0, 2),
                    fmt_num(float(cold.get("estimated_tune_cache_bytes") or 0) / (1024 ** 3), 2),
                    fmt_num(float(cold.get("estimated_confirmation_minutes") or 0) / 60.0, 2),
                    fmt_num(float(cold.get("estimated_confirmation_cache_bytes") or 0) / (1024 ** 3), 2),
                ],
                [
                    "preferred isolated sigma refinement, reuse",
                    preferred.get("new_tune_arms"),
                    fmt_num(float(preferred.get("estimated_tune_minutes") or 0) / 60.0, 2),
                    fmt_num(float(preferred.get("estimated_tune_cache_bytes") or 0) / (1024 ** 3), 2),
                    "-",
                    "-",
                ],
            ],
        ),
        "",
        "The expanded tune may use only the old development/tune dates. The original H1 holdout and this fresh panel are forbidden selection inputs. After tune-only selection is frozen, the fresh panel may be opened once for one fixed confirmation with no reselection.",
        "",
        "## Sigma Unit Contract",
        "",
        f"H1's sigma `{unit_semantics.get('h1_sigma_numeric')}` is `{unit_semantics.get('toronto_bandwidth')}` for Toronto but `{unit_semantics.get('f_market_bandwidth')}` = `{fmt_num(unit_semantics.get('f_market_bandwidth_c_equivalent'), 4)} C` for F markets. The physical bandwidth therefore differs by `{unit_semantics.get('physical_bandwidth_ratio_c_to_f')}x`.",
        "",
        "The existing result remains valid as an equal-native-bucket treatment, not as a common-physical-bandwidth result. A fresh refinement must predeclare physical-C anchors with `sigma_F = 1.8 * sigma_C`, or separate explicitly labeled family grids. A shared numeric native-unit grid must not be described as physically comparable.",
        "",
        "## Technical Blockers",
        "",
        *(f"- {reason}" for reason in (payload.get("technical_blockers") or ["none"])),
        "",
        "## Provenance and Safety",
        "",
        f"- Scratch corpus hash: `{(payload.get('manifest') or {}).get('corpus_hash')}`",
        f"- Read-only snapshots: `{(payload.get('inputs') or {}).get('snapshots_root')}`",
        "- Tier 1 exact current identity is a full identity-hash comparison for the captured active model kind and is never inferred from Tier 2.",
        "- Tier 2 replays distributions only; no settlement outcome or market-band score is opened.",
        "- This audit does not authorize tuning, serving, promotion, or trading.",
        "",
    ]
    return "\n".join(lines)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    temporary.write_text(content if content.endswith("\n") else content + "\n", encoding="utf-8")
    os.replace(temporary, path)


def write_outputs(
    payload: Mapping[str, Any], manifest: Mapping[str, Any], paths: Mapping[str, Path]
) -> None:
    _atomic_write(paths["manifest_out"], json.dumps(manifest, indent=2, sort_keys=True))
    manifest_hash = _sha256_stable(paths["manifest_out"])
    enriched = dict(payload)
    enriched["outputs"] = dict(payload.get("outputs") or {})
    enriched["outputs"]["manifest_sha256"] = manifest_hash
    _atomic_write(paths["json_out"], json.dumps(enriched, indent=2, sort_keys=True))
    _atomic_write(paths["report_out"], render_report(enriched))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit a later, read-only 12-market panel for fixed H1 confirmation feasibility."
    )
    parser.add_argument("--snapshots-root", required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--manifest-out", required=True)
    parser.add_argument("--json-out", required=True)
    parser.add_argument("--report-out", required=True)
    parser.add_argument("--sigma-grid", default=",".join(map(str, DEFAULT_SIGMAS)))
    parser.add_argument("--weight-grid", default=",".join(map(str, DEFAULT_WEIGHTS)))
    parser.add_argument("--existing-sigma", type=float, default=0.75)
    parser.add_argument("--old-tune-dates", type=int, default=17)
    parser.add_argument("--measured-tune-arm-minutes", type=float, required=True)
    parser.add_argument("--measured-tune-cache-bytes", type=int, required=True)
    parser.add_argument("--reference-holdout-dates", type=int, required=True)
    parser.add_argument("--measured-holdout-arm-minutes", type=float, required=True)
    parser.add_argument("--measured-holdout-cache-bytes", type=int, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload, manifest, paths = run_audit(args)
        write_outputs(payload, manifest, paths)
    except (FreshConfirmationAuditError, OSError, ValueError) as exc:
        print(f"Fresh confirmation audit blocked: {exc}", file=sys.stderr)
        return 2
    print(
        "Fresh confirmation audit "
        f"{payload.get('audit_disposition')}: {paths['json_out']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
