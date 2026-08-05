"""Durable model-versus-market skill tracking from served snapshot tapes.

The tracker is deliberately observational.  It reads the authoritative
settlement ledgers and served ``snapshots_long.csv`` projections, then appends
revisioned score records.  It never fits, promotes, trades, or rewrites prior
reported history.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd
from scipy.stats import nct, t

from weather.backtesting.settlement_ledger import (
    current_ledger_label,
    ledger_path_for_market,
    verify_ledger_history,
)
from weather.io import (
    acquire_writer_lock,
    read_jsonl,
    release_writer_lock,
    write_json_atomic,
    write_text_atomic,
)
from weather.market.market_registry import all_specs, spec_for_id
from weather.paths import data_path, docs_path
from weather.reporting.research.skill_gap_decomposition import (
    isotonic_murphy_decomposition,
)
from weather.reporting.scorecards.model_history import summarize_market_day
from weather.schema_registry import schema_version


HISTORY_SCHEMA_VERSION = schema_version("model_market_skill_history")
SUMMARY_SCHEMA_VERSION = schema_version("model_market_skill_summary")
TOOL_LOGIC_VERSION = "model_market_skill_tracker_logic_1"
DEFAULT_HISTORY_PATH = data_path("backtest", "model_market_skill_history.jsonl")
DEFAULT_SUMMARY_PATH = data_path("backtest", "model_market_skill_summary.json")
DEFAULT_REPORT_PATH = data_path("backtest", "model_market_skill_report.md")
DEFAULT_SNAPSHOTS_ROOT = data_path("snapshots")
DEFAULT_SETTLEMENT_ROOT = data_path("settlements")
DEFAULT_RESERVATION_PATH = docs_path("operations", "reserved-confirmation-window.md")
FLOOR_REGIME_ANCHOR = "b77cfbed49ee85cc0009a2058e842dda08036272"
HARD_FLOOR_REGIME = "hard_rescued_floor_" + "v1"
SLICES = {
    "all_market_local_capture_hours": lambda row: True,
    "market_local_capture_09_14": lambda row: (
        row.get("cutoff_hour") is not None and 9 <= int(row["cutoff_hour"]) <= 14
    ),
}
ALPHA = 0.05
TARGET_POWER = 0.80
DEFAULT_REPLICATES = 2_000
DEFAULT_SEED = 3_215_258_335
PROBABILITY_TOLERANCE = 1e-6
SIMPLEX_TOLERANCE = 2e-4
NOT_DISTINGUISHABLE = (
    "This week-over-week delta is not statistically distinguishable from zero."
)


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def _digest_payload(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_prefix(path: Path, size_bytes: int) -> str:
    digest = hashlib.sha256()
    remaining = int(size_bytes)
    with path.open("rb") as handle:
        while remaining > 0:
            chunk = handle.read(min(1024 * 1024, remaining))
            if not chunk:
                raise RuntimeError(f"file truncated while hashing retained prefix: {path}")
            digest.update(chunk)
            remaining -= len(chunk)
    return digest.hexdigest()


def _file_state(path: Path, *, include_sha256: bool = False) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False}
    stat = path.stat()
    state = {
        "path": str(path),
        "exists": True,
        "size_bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }
    if include_sha256:
        state["sha256"] = _sha256(path)
    return state


def _stable_seed(label: str, base_seed: int) -> int:
    offset = int(hashlib.sha256(label.encode("utf-8")).hexdigest()[:8], 16)
    return (int(base_seed) + offset) % (2**32 - 1)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def reservation_guard(path: str | Path = DEFAULT_RESERVATION_PATH) -> dict[str, Any]:
    """Read the reservation contract before any evidence path is enumerated."""

    reservation_path = Path(path)
    text = reservation_path.read_text(encoding="utf-8")
    normalized = " ".join(text.upper().split())
    inactive = (
        "NONE ARE CURRENTLY RESERVED" in normalized
        and "NO DATE IS HELD OUT TODAY" in normalized
    )
    if not inactive:
        raise RuntimeError(
            "reserved confirmation window is active or ambiguous; refusing to read "
            "settlement or snapshot evidence"
        )
    return {
        "status": "PASS_NO_DATES_RESERVED",
        "path": str(reservation_path),
        "sha256": _sha256(reservation_path),
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def _labels_from_ledger(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    rows = read_jsonl(path, skip_invalid=False)
    verification = verify_ledger_history(rows)
    if verification["status"] != "PASS":
        codes = ",".join(item["code"] for item in verification["blockers"])
        raise RuntimeError(f"settlement ledger integrity failure at {path}: {codes}")
    slugs = sorted({str(row.get("event_slug")) for row in rows if row.get("event_slug")})
    labels = {slug: _compact_label(current_ledger_label(rows, slug)) for slug in slugs}
    return labels, {
        **_file_state(path, include_sha256=True),
        "record_count": verification["record_count"],
        "revision_count": verification["revision_count"],
        "tail_sha256": _digest_payload(rows[-1]) if rows else None,
    }


def _compact_label(label: dict[str, Any] | None) -> dict[str, Any]:
    """Retain only fields needed to rescore a market-day after a restart."""

    fields = (
        "event_slug",
        "market_id",
        "city",
        "target_date",
        "revision_id",
        "revision_number",
        "label_hash",
        "settlement_bucket",
        "settlement_unit",
        "winning_band",
        "quality_grade",
        "quality_reason",
        "coverage_clean",
        "capture_ratio",
        "max_gap_minutes",
        "material_coverage_grade",
        "promotion_countable",
        "promotion_countable_reason",
        "settlement_source",
        "finalized_at_utc",
    )
    return {field: (label or {}).get(field) for field in fields}


def load_settlement_inventory(
    settlement_root: Path,
    prior_summary: dict[str, Any] | None,
    *,
    full: bool,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Load all labels on backfill and only changed physical ledgers on refresh."""

    prior_summary = prior_summary or {}
    prior_states = prior_summary.get("ledger_states") or {}
    prior_labels = prior_summary.get("settlement_labels") or {}
    labels: dict[str, dict[str, Any]] = {}
    states: dict[str, Any] = {}
    for spec in all_specs():
        path = ledger_path_for_market(spec.id, settlement_root)
        current_state = _file_state(path)
        prior_state = prior_states.get(spec.id) or {}
        unchanged = (
            not full
            and current_state.get("exists")
            and current_state.get("size_bytes") == prior_state.get("size_bytes")
            and current_state.get("mtime_ns") == prior_state.get("mtime_ns")
        )
        if unchanged:
            market_labels = {
                slug: dict(label)
                for slug, label in prior_labels.items()
                if label.get("market_id") == spec.id
            }
            if not market_labels and prior_state.get("record_count"):
                raise RuntimeError(
                    f"refresh checkpoint lacks compact labels for unchanged ledger {spec.id}"
                )
            labels.update(market_labels)
            states[spec.id] = dict(prior_state)
            continue
        if not full and prior_state.get("exists"):
            prior_size = int(prior_state.get("size_bytes") or 0)
            if not current_state.get("exists") or int(current_state.get("size_bytes") or 0) < prior_size:
                raise RuntimeError(f"append-only settlement ledger disappeared or shrank: {path}")
            prior_sha = prior_state.get("sha256")
            if not prior_sha or _sha256_prefix(path, prior_size) != prior_sha:
                raise RuntimeError(f"append-only settlement ledger prefix changed: {path}")
        if not path.exists():
            states[spec.id] = current_state
            continue
        market_labels, verified_state = _labels_from_ledger(path)
        labels.update(market_labels)
        states[spec.id] = verified_state
    return labels, states


def _normalize_commit(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    for token in text.replace("dirty", " ").replace("+", " ").split():
        if len(token) >= 7 and all(char in "0123456789abcdef" for char in token):
            return token[:40]
    return None


def _git_is_ancestor(older: str, newer: str, repo_root: Path) -> bool | None:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", older, newer],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    return None


def artifact_regime(row: dict[str, Any], repo_root: Path, cache: dict[str, str]) -> str:
    commit = _normalize_commit(row.get("runtime_git_commit"))
    dirty = _as_bool(row.get("runtime_git_dirty")) or "dirty" in str(
        row.get("runtime_code_state") or ""
    ).lower()
    fingerprint = str(row.get("runtime_source_fingerprint") or "").strip()
    identity = commit or fingerprint or "missing-runtime-identity"
    if dirty or commit is None:
        return f"unclassified_runtime:{identity}"
    if commit in cache:
        return cache[commit]
    after = _git_is_ancestor(FLOOR_REGIME_ANCHOR, commit, repo_root)
    before = _git_is_ancestor(commit, FLOOR_REGIME_ANCHOR, repo_root)
    if after is True:
        regime = HARD_FLOOR_REGIME
    elif before is True:
        regime = "legacy_pre_hard_rescued_floor"
    else:
        regime = f"unclassified_runtime:{identity}"
    cache[commit] = regime
    return regime


def _validate_scoring_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    blockers = []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("snapshot_id"))].append(row)
    for snapshot_id, snapshot_rows in grouped.items():
        model = [float(row["model_probability"]) for row in snapshot_rows]
        market = [float(row["market_yes"]) for row in snapshot_rows]
        outcomes = [int(row["outcome"]) for row in snapshot_rows]
        if any(value < -PROBABILITY_TOLERANCE or value > 1 + PROBABILITY_TOLERANCE for value in model):
            blockers.append({"snapshot_id": snapshot_id, "code": "model_probability_out_of_range"})
        if any(value < -PROBABILITY_TOLERANCE or value > 1 + PROBABILITY_TOLERANCE for value in market):
            blockers.append({"snapshot_id": snapshot_id, "code": "market_probability_out_of_range"})
        if abs(sum(model) - 1.0) > SIMPLEX_TOLERANCE:
            blockers.append({
                "snapshot_id": snapshot_id,
                "code": "model_probability_mass_invalid",
                "sum": sum(model),
            })
        if sum(outcomes) != 1:
            blockers.append({
                "snapshot_id": snapshot_id,
                "code": "winner_identity_invalid",
                "winner_count": sum(outcomes),
            })
    return {
        "status": "PASS" if not blockers else "BLOCK",
        "snapshot_count": len(grouped),
        "blockers": blockers[:50],
        "blocker_count": len(blockers),
    }


def _decomposition(rows: list[dict[str, Any]], probability_key: str) -> dict[str, Any]:
    return isotonic_murphy_decomposition(
        (float(row[probability_key]), int(row["outcome"])) for row in rows
    )


def _runtime_identity(rows: Iterable[dict[str, Any]]) -> dict[str, list[str]]:
    fields = (
        "runtime_git_commit",
        "runtime_source_fingerprint",
        "runtime_code_state",
    )
    return {
        field: sorted({str(row.get(field)) for row in rows if row.get(field) not in (None, "")})
        for field in fields
    }


def _market_day_payloads(
    label: dict[str, Any],
    snapshots_root: Path,
    repo_root: Path,
    regime_cache: dict[str, str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    market_id = str(label["market_id"])
    spec = spec_for_id(market_id)
    target = date.fromisoformat(str(label["target_date"]))
    event_slug = str(label["event_slug"])
    folder = snapshots_root / event_slug
    tape = folder / "snapshots_long.csv"
    tape_state = _file_state(tape, include_sha256=tape.exists())
    if not tape.exists():
        return [], tape_state
    day, rows = summarize_market_day(folder, spec, target, label=label)
    if day.get("status") != "scored":
        return [], tape_state
    validation = _validate_scoring_rows(rows)
    if validation["status"] != "PASS":
        raise RuntimeError(
            f"invalid probability/outcome identity in {tape}: "
            f"{json.dumps(validation['blockers'], sort_keys=True)}"
        )

    by_regime: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_regime[artifact_regime(row, repo_root, regime_cache)].append(row)
    output = []
    for regime, regime_rows in sorted(by_regime.items()):
        for slice_id, predicate in SLICES.items():
            selected = [row for row in regime_rows if predicate(row)]
            if not selected:
                continue
            model = _decomposition(selected, "model_probability")
            market = _decomposition(selected, "market_yes")
            market_brier = market["brier"]
            output.append({
                "record_type": "market_day_skill_revision",
                "status": "promotion_countable",
                "market_id": market_id,
                "city": spec.city_label,
                "target_date": target.isoformat(),
                "week_start": (target - timedelta(days=target.weekday())).isoformat(),
                "event_slug": event_slug,
                "artifact_regime": regime,
                "capture_slice": slice_id,
                "capture_slice_definition": (
                    "all served snapshot capture hours in market local time"
                    if slice_id == "all_market_local_capture_hours"
                    else "served snapshots captured from 09:00 through 14:59 in market local time"
                ),
                "model_brier": model["brier"],
                "market_brier": market_brier,
                "model_over_market_brier_ratio": (
                    model["brier"] / market_brier if market_brier else None
                ),
                "model_minus_market_brier_gap": model["brier"] - market_brier,
                "model_decomposition": model,
                "market_decomposition": market,
                "identity_contract": (
                    "brier = reliability - resolution + uncertainty + identity_residual"
                ),
                "scored_band_rows": len(selected),
                "snapshot_count": len({row.get("snapshot_id") for row in selected}),
                "probability_identity_validation": validation,
                "runtime_identity": _runtime_identity(selected),
                "settlement": {
                    "authority": "data/settlements/<market>/ledger.jsonl",
                    "revision_id": label.get("revision_id"),
                    "revision_number": label.get("revision_number"),
                    "label_hash": label.get("label_hash"),
                    "settlement_bucket": label.get("settlement_bucket"),
                    "settlement_unit": label.get("settlement_unit"),
                    "settlement_source": label.get("settlement_source"),
                    "promotion_countable": _as_bool(label.get("promotion_countable")),
                    "promotion_countable_reason": label.get("promotion_countable_reason"),
                },
                "tape": tape_state,
                "tool_logic_version": TOOL_LOGIC_VERSION,
            })
    return output, tape_state


def _record_key(record: dict[str, Any]) -> str:
    if record["record_type"] == "market_day_skill_revision":
        parts = (
            record["market_id"],
            record["target_date"],
            record["artifact_regime"],
            record["capture_slice"],
        )
    else:
        parts = (record["week_start"], record["artifact_regime"], record["capture_slice"])
    return "|".join(str(value) for value in parts)


def _source_fingerprint(record: dict[str, Any]) -> str:
    excluded = {
        "schema_version",
        "revision_id",
        "revision_number",
        "recorded_at_utc",
        "supersedes_revision_id",
        "previous_record_hash",
        "record_hash",
        "source_fingerprint",
    }
    return _digest_payload({key: value for key, value in record.items() if key not in excluded})


def _verify_history(rows: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], str | None]:
    current: dict[str, dict[str, Any]] = {}
    previous_hash = None
    for index, row in enumerate(rows):
        payload = {key: value for key, value in row.items() if key != "record_hash"}
        observed_hash = _digest_payload(payload)
        if row.get("previous_record_hash") != previous_hash:
            raise RuntimeError(f"skill history chain break at record {index}")
        if row.get("record_hash") != observed_hash:
            raise RuntimeError(f"skill history record hash mismatch at record {index}")
        key = row.get("record_key")
        previous = current.get(key)
        if previous and row.get("supersedes_revision_id") != previous.get("revision_id"):
            raise RuntimeError(f"skill history supersession break for {key}")
        current[key] = row
        previous_hash = row["record_hash"]
    return current, previous_hash


def _append_revisions(
    history_path: Path,
    candidates: list[dict[str, Any]],
    current: dict[str, dict[str, Any]],
    previous_hash: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    appended = []
    now = datetime.now(timezone.utc).isoformat()
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("a", encoding="utf-8", newline="\n") as handle:
        for candidate in candidates:
            record = dict(candidate)
            key = _record_key(record)
            fingerprint = _source_fingerprint(record)
            prior = current.get(key)
            if prior and prior.get("source_fingerprint") == fingerprint:
                continue
            revision_number = int((prior or {}).get("revision_number") or 0) + 1
            revision_seed = {
                "record_key": key,
                "revision_number": revision_number,
                "recorded_at_utc": now,
                "source_fingerprint": fingerprint,
                "supersedes_revision_id": (prior or {}).get("revision_id"),
            }
            record.update({
                "schema_version": HISTORY_SCHEMA_VERSION,
                "record_key": key,
                "source_fingerprint": fingerprint,
                "revision_id": f"sha256:{_digest_payload(revision_seed)}",
                "revision_number": revision_number,
                "recorded_at_utc": now,
                "supersedes_revision_id": (prior or {}).get("revision_id"),
                "previous_record_hash": previous_hash,
            })
            record["record_hash"] = _digest_payload(record)
            handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            previous_hash = record["record_hash"]
            current[key] = record
            appended.append(record)
    return appended, previous_hash


def _support(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "date_clusters": len({row["target_date"] for row in rows}),
        "market_clusters": len({row["market_id"] for row in rows}),
        "market_days": len(rows),
    }


def _crossed_draws(
    rows: list[dict[str, Any]],
    value_fn: Callable[[list[dict[str, Any]], np.ndarray], float],
    *,
    replicates: int,
    seed: int,
) -> tuple[float | None, np.ndarray, dict[str, int]]:
    support = _support(rows)
    if not rows:
        return None, np.asarray([], dtype=float), support
    dates = sorted({row["target_date"] for row in rows})
    markets = sorted({row["market_id"] for row in rows})
    date_map = {value: index for index, value in enumerate(dates)}
    market_map = {value: index for index, value in enumerate(markets)}
    date_index = np.asarray([date_map[row["target_date"]] for row in rows])
    market_index = np.asarray([market_map[row["market_id"]] for row in rows])
    equal = np.ones(len(rows), dtype=float)
    point = value_fn(rows, equal)
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(int(replicates)):
        date_counts = np.bincount(
            rng.integers(0, len(dates), len(dates)), minlength=len(dates)
        )
        market_counts = np.bincount(
            rng.integers(0, len(markets), len(markets)), minlength=len(markets)
        )
        weights = date_counts[date_index] * market_counts[market_index]
        if weights.sum() > 0:
            value = value_fn(rows, weights.astype(float))
            if value is not None and math.isfinite(value):
                draws.append(value)
    return point, np.asarray(draws, dtype=float), support


def _mean_value(field: str) -> Callable[[list[dict[str, Any]], np.ndarray], float]:
    def calculate(rows: list[dict[str, Any]], weights: np.ndarray) -> float:
        values = np.asarray([float(row[field]) for row in rows])
        return float(np.dot(weights, values) / weights.sum())

    return calculate


def _ratio_value(rows: list[dict[str, Any]], weights: np.ndarray) -> float:
    model = np.asarray([float(row["model_brier"]) for row in rows])
    market = np.asarray([float(row["market_brier"]) for row in rows])
    denominator = float(np.dot(weights, market))
    return float(np.dot(weights, model) / denominator)


def _inference(
    rows: list[dict[str, Any]],
    field: str,
    *,
    replicates: int,
    seed: int,
    value_fn: Callable[[list[dict[str, Any]], np.ndarray], float] | None = None,
) -> dict[str, Any]:
    point, draws, support = _crossed_draws(
        rows,
        value_fn or _mean_value(field),
        replicates=replicates,
        seed=seed,
    )
    interval = (
        [float(value) for value in np.quantile(draws, [0.025, 0.975])]
        if len(draws)
        else [None, None]
    )
    bootstrap_se = float(draws.std(ddof=1)) if len(draws) > 1 else None
    return {
        "point": point,
        "interval_95": interval,
        "bootstrap_standard_error": bootstrap_se,
        "fleet_date_equivalent_standard_deviation": (
            bootstrap_se * math.sqrt(support["date_clusters"])
            if bootstrap_se is not None
            else None
        ),
        **support,
        "cluster_method": "independent target-date and market pigeonhole bootstrap",
        "replicates": int(replicates),
        "seed": int(seed),
    }


def _minimum_detectable_effect(
    n_dates: int,
    n_markets: int,
    standard_deviation: float | None,
) -> dict[str, Any]:
    if n_dates < 2 or n_markets < 2 or not standard_deviation or standard_deviation <= 0:
        return {
            "value": None,
            "status": "UNAVAILABLE_INSUFFICIENT_OR_DEGENERATE_CLUSTER_VARIANCE",
            "alpha": ALPHA,
            "target_power": TARGET_POWER,
        }
    degrees_of_freedom = min(n_dates - 1, n_markets - 1)
    critical = float(t.ppf(1.0 - ALPHA, degrees_of_freedom))

    def power(effect: float) -> float:
        noncentrality = effect * math.sqrt(n_dates) / standard_deviation
        return float(1.0 - nct.cdf(critical, degrees_of_freedom, noncentrality))

    lower = 0.0
    upper = standard_deviation
    while power(upper) < TARGET_POWER:
        upper *= 2.0
    for _ in range(80):
        midpoint = (lower + upper) / 2.0
        if power(midpoint) >= TARGET_POWER:
            upper = midpoint
        else:
            lower = midpoint
    return {
        "value": upper,
        "status": "ESTIMATED",
        "alpha": ALPHA,
        "target_power": TARGET_POWER,
        "test": "one-sided noncentral t over fleet-date equivalents",
        "degrees_of_freedom": degrees_of_freedom,
    }


def _week_contrast(
    current_rows: list[dict[str, Any]],
    prior_rows: list[dict[str, Any]],
    *,
    replicates: int,
    seed: int,
) -> dict[str, Any]:
    if not current_rows or not prior_rows:
        return {"status": "NO_COMPARABLE_PRIOR_WEEK", "statement": "No comparable prior week is available."}
    shared_markets = sorted(
        {row["market_id"] for row in current_rows}
        & {row["market_id"] for row in prior_rows}
    )
    current_rows = [row for row in current_rows if row["market_id"] in shared_markets]
    prior_rows = [row for row in prior_rows if row["market_id"] in shared_markets]
    if not current_rows or not prior_rows:
        return {"status": "NO_SHARED_MARKET_SUPPORT", "statement": "No shared market support is available."}
    markets = shared_markets
    market_map = {value: index for index, value in enumerate(markets)}
    rng = np.random.default_rng(seed)
    draws = []
    periods = (prior_rows, current_rows)
    for _ in range(int(replicates)):
        market_counts = np.bincount(
            rng.integers(0, len(markets), len(markets)), minlength=len(markets)
        )
        means = []
        valid = True
        for rows in periods:
            dates = sorted({row["target_date"] for row in rows})
            date_map = {value: index for index, value in enumerate(dates)}
            date_counts = np.bincount(
                rng.integers(0, len(dates), len(dates)), minlength=len(dates)
            )
            weights = np.asarray([
                date_counts[date_map[row["target_date"]]]
                * market_counts[market_map[row["market_id"]]]
                for row in rows
            ], dtype=float)
            if weights.sum() <= 0:
                valid = False
                break
            values = np.asarray([row["model_minus_market_brier_gap"] for row in rows])
            means.append(float(np.dot(weights, values) / weights.sum()))
        if valid:
            draws.append(means[1] - means[0])
    point = float(np.mean([row["model_minus_market_brier_gap"] for row in current_rows])) - float(
        np.mean([row["model_minus_market_brier_gap"] for row in prior_rows])
    )
    interval = [float(value) for value in np.quantile(draws, [0.025, 0.975])]
    indistinguishable = interval[0] <= 0 <= interval[1]
    if indistinguishable:
        statement = NOT_DISTINGUISHABLE
    elif point < 0:
        statement = "The model-minus-market Brier gap improved week over week."
    else:
        statement = "The model-minus-market Brier gap worsened week over week."
    return {
        "status": "NOT_STATISTICALLY_DISTINGUISHABLE" if indistinguishable else "DISTINGUISHABLE",
        "contrast": "current week minus prior week model-minus-market Brier gap",
        "point": point,
        "interval_95": interval,
        "statement": statement,
        "current_support": _support(current_rows),
        "prior_support": _support(prior_rows),
        "shared_market_clusters": len(markets),
        "cluster_method": "independent dates within week and shared market draw",
        "replicates": int(replicates),
        "seed": int(seed),
    }


def weekly_payloads(
    market_days: list[dict[str, Any]],
    *,
    replicates: int,
    base_seed: int,
) -> list[dict[str, Any]]:
    countable = [row for row in market_days if row.get("status") == "promotion_countable"]
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in countable:
        groups[(row["week_start"], row["artifact_regime"], row["capture_slice"])].append(row)
    output = []
    for (week_start, regime, capture_slice), rows in sorted(groups.items()):
        label = "|".join((week_start, regime, capture_slice))
        metrics = {
            "model_brier": _inference(
                rows, "model_brier", replicates=replicates,
                seed=_stable_seed(label + "|model", base_seed),
            ),
            "market_brier": _inference(
                rows, "market_brier", replicates=replicates,
                seed=_stable_seed(label + "|market", base_seed),
            ),
            "model_minus_market_brier_gap": _inference(
                rows, "model_minus_market_brier_gap", replicates=replicates,
                seed=_stable_seed(label + "|gap", base_seed),
            ),
            "model_over_market_brier_ratio": _inference(
                rows, "model_over_market_brier_ratio", replicates=replicates,
                seed=_stable_seed(label + "|ratio", base_seed), value_fn=_ratio_value,
            ),
        }
        for owner in ("model", "market"):
            for component in ("reliability", "resolution", "uncertainty", "identity_residual"):
                projected = [
                    {**row, "_component": row[f"{owner}_decomposition"][component]}
                    for row in rows
                ]
                metrics[f"{owner}_{component}"] = _inference(
                    projected,
                    "_component",
                    replicates=replicates,
                    seed=_stable_seed(label + f"|{owner}|{component}", base_seed),
                )
        prior_week = (date.fromisoformat(week_start) - timedelta(days=7)).isoformat()
        prior_rows = groups.get((prior_week, regime, capture_slice), [])
        gap_inference = metrics["model_minus_market_brier_gap"]
        output.append({
            "record_type": "weekly_skill_revision",
            "status": "weekly_equal_market_day_aggregate",
            "week_start": week_start,
            "week_end": (date.fromisoformat(week_start) + timedelta(days=6)).isoformat(),
            "artifact_regime": regime,
            "capture_slice": capture_slice,
            "weighting": "equal promotion-countable market-day",
            "support": _support(rows),
            "metrics": metrics,
            "minimum_detectable_model_minus_market_brier_gap": _minimum_detectable_effect(
                gap_inference["date_clusters"],
                gap_inference["market_clusters"],
                gap_inference["fleet_date_equivalent_standard_deviation"],
            ),
            "week_over_week": _week_contrast(
                rows,
                prior_rows,
                replicates=replicates,
                seed=_stable_seed(label + "|week_over_week", base_seed),
            ),
            "source_market_day_revision_ids": sorted(row["revision_id"] for row in rows),
            "tool_logic_version": TOOL_LOGIC_VERSION,
        })
    return output


def _csv_crossed_ratio_delta(
    frame: pd.DataFrame,
    *,
    replicates: int,
    seed: int,
) -> dict[str, Any]:
    baseline = frame["baseline_current_brier"].to_numpy(dtype=float)
    hard = frame["hard_current_brier"].to_numpy(dtype=float)
    market = frame["market_brier"].to_numpy(dtype=float)
    dates = frame["target_date"].astype(str).to_numpy()
    markets = frame["market_id"].astype(str).to_numpy()
    unique_dates = sorted(np.unique(dates))
    unique_markets = sorted(np.unique(markets))
    date_map = {value: index for index, value in enumerate(unique_dates)}
    market_map = {value: index for index, value in enumerate(unique_markets)}
    date_index = np.asarray([date_map[value] for value in dates])
    market_index = np.asarray([market_map[value] for value in markets])
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(int(replicates)):
        date_counts = np.bincount(rng.integers(0, len(unique_dates), len(unique_dates)), minlength=len(unique_dates))
        market_counts = np.bincount(rng.integers(0, len(unique_markets), len(unique_markets)), minlength=len(unique_markets))
        weights = date_counts[date_index] * market_counts[market_index]
        denominator = float(np.dot(weights, market))
        if denominator > 0:
            draws.append(float(np.dot(weights, hard) / denominator - np.dot(weights, baseline) / denominator))
    baseline_ratio = float(baseline.sum() / market.sum())
    hard_ratio = float(hard.sum() / market.sum())
    interval = [float(value) for value in np.quantile(draws, [0.025, 0.975])]
    reproduced = (
        abs(baseline_ratio - 1.663915842514083) < 5e-6
        and abs(hard_ratio - 1.497960058043435) < 5e-6
        and interval[1] < 0
    )
    return {
        "status": "PASS" if reproduced else "FAIL",
        "baseline_model_over_market_brier_ratio": baseline_ratio,
        "hard_floor_model_over_market_brier_ratio": hard_ratio,
        "hard_minus_baseline_ratio_delta": hard_ratio - baseline_ratio,
        "hard_minus_baseline_crossed_interval_95": interval,
        "date_clusters": len(unique_dates),
        "market_clusters": len(unique_markets),
        "market_days": int(frame[["target_date", "market_id"]].drop_duplicates().shape[0]),
        "snapshot_rows": len(frame),
        "replicates": int(replicates),
        "seed": int(seed),
    }


def _csv_crossed_mean(
    frame: pd.DataFrame,
    column: str,
    *,
    replicates: int,
    seed: int,
) -> dict[str, Any]:
    rows = frame[["target_date", "market_id", column]].rename(columns={column: "value"}).to_dict("records")
    point, draws, support = _crossed_draws(
        rows,
        lambda selected, weights: float(np.dot(weights, np.asarray([row["value"] for row in selected])) / weights.sum()),
        replicates=replicates,
        seed=seed,
    )
    interval = [float(value) for value in np.quantile(draws, [0.025, 0.975])]
    expected = (-0.6640809099217561, -1.1164176909999597, -0.24818083563233753)
    return {
        "status": "PASS" if abs(point - expected[0]) < 5e-6 and abs(interval[0] - expected[1]) < 5e-6 and abs(interval[1] - expected[2]) < 5e-6 else "FAIL",
        "raw_hgb_bias_c_equivalent": point,
        "crossed_interval_95": interval,
        **support,
        "market_days": int(frame[["target_date", "market_id"]].drop_duplicates().shape[0]),
        "selected_hour_rows": len(frame),
        "replicates": int(replicates),
        "seed": int(seed),
    }


def positive_controls(
    floor_rows_path: Path | None,
    cool_bias_rows_path: Path | None,
    *,
    replicates: int,
    seed: int,
    prior: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if floor_rows_path is None and cool_bias_rows_path is None:
        return prior or {"status": "NOT_RUN_INPUTS_NOT_SUPPLIED"}
    if floor_rows_path is None or cool_bias_rows_path is None:
        raise RuntimeError("both positive-control inputs must be supplied together")
    floor = pd.read_csv(floor_rows_path, usecols=[
        "target_date", "market_id", "baseline_current_brier", "hard_current_brier", "market_brier"
    ])
    cool = pd.read_csv(cool_bias_rows_path, usecols=[
        "target_date", "market_id", "raw_bias_c_equivalent"
    ])
    floor_result = _csv_crossed_ratio_delta(floor, replicates=replicates, seed=seed)
    cool_result = _csv_crossed_mean(cool, "raw_bias_c_equivalent", replicates=replicates, seed=seed)
    return {
        "status": "PASS" if floor_result["status"] == cool_result["status"] == "PASS" else "FAIL",
        "floor_fix": {**floor_result, "source": {**_file_state(floor_rows_path), "sha256": _sha256(floor_rows_path)}},
        "cool_hgb_bias": {**cool_result, "source": {**_file_state(cool_bias_rows_path), "sha256": _sha256(cool_bias_rows_path)}},
    }


def _render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Model-vs-market skill tracker",
        "",
        f"Generated: `{summary['generated_at_utc']}`",
        "",
        "This report uses promotion-countable settlement-ledger labels and served snapshot tapes. "
        "It is observational evidence, not a promotion decision or proof of edge.",
        "",
        f"Positive controls: **{summary['positive_controls']['status']}**.",
        "",
        "## Weekly series",
        "",
        "| Week | Regime | Slice | D | M | Market-days | Model Brier | Market Brier | Ratio | Gap | MDE | Week-over-week |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    weekly = sorted(summary.get("current_weekly") or [], key=lambda row: (row["week_start"], row["artifact_regime"], row["capture_slice"]))
    for row in weekly:
        support = row["support"]
        metrics = row["metrics"]
        mde = row["minimum_detectable_model_minus_market_brier_gap"].get("value")
        fmt = lambda value: "-" if value is None else f"{float(value):.6f}"
        lines.append(
            f"| {row['week_start']} | {row['artifact_regime']} | {row['capture_slice']} | "
            f"{support['date_clusters']} | {support['market_clusters']} | {support['market_days']} | "
            f"{fmt(metrics['model_brier']['point'])} | {fmt(metrics['market_brier']['point'])} | "
            f"{fmt(metrics['model_over_market_brier_ratio']['point'])} | "
            f"{fmt(metrics['model_minus_market_brier_gap']['point'])} | {fmt(mde)} | "
            f"{row['week_over_week']['statement']} |"
        )
    if not weekly:
        lines.append("| - | - | - | 0 | 0 | 0 | - | - | - | - | - | No countable records. |")
    lines.extend([
        "",
        "All uncertainty intervals use independent target-date and market pigeonhole resampling. "
        "The 09:00–14:00 lane is market-local capture time and is reported separately; it is not "
        "described as an effective Weather Underground print cutoff.",
        "",
    ])
    return "\n".join(lines)


def run_tracker(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    reservation = reservation_guard(args.reservation_path)
    history_path = Path(args.history_path)
    summary_path = Path(args.summary_path)
    report_path = Path(args.report_path)
    prior_summary = None
    if summary_path.exists():
        prior_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if args.command == "refresh" and prior_summary is None:
        raise RuntimeError("refresh requires an existing backfill checkpoint; run backfill manually in the quiet window")
    allow_missing_controls = bool(getattr(args, "allow_missing_positive_controls", False))
    controls_supplied = bool(args.floor_control_rows and args.cool_bias_control_rows)
    prior_controls_pass = (prior_summary or {}).get("positive_controls", {}).get("status") == "PASS"
    if not controls_supplied and not allow_missing_controls:
        if args.command == "backfill" or not prior_controls_pass:
            raise RuntimeError(
                "a backfill checkpoint requires both passing positive-control inputs; "
                "refresh may reuse only a prior PASS"
            )

    lock = acquire_writer_lock(
        summary_path,
        owner={"tool": "model_market_skill_tracker", "command": args.command},
        attempts=1,
        stale_after_seconds=4 * 60 * 60,
    )
    if not lock:
        raise RuntimeError(f"another skill tracker writer owns {summary_path}")
    try:
        existing_rows = read_jsonl(history_path, skip_invalid=False)
        current, previous_hash = _verify_history(existing_rows)
        labels, ledger_states = load_settlement_inventory(
            Path(args.settlement_root), prior_summary, full=args.command == "backfill"
        )
        prior_tapes = (prior_summary or {}).get("tape_states") or {}
        tape_states = dict(prior_tapes)
        current_market_days = {
            key: value for key, value in ((prior_summary or {}).get("current_market_days") or {}).items()
        }
        candidates = []
        processed_slugs: set[str] = set()
        regime_cache: dict[str, str] = {}
        eligible_labels = [
            label for label in labels.values()
            if label and _as_bool(label.get("promotion_countable"))
        ]
        for label in sorted(eligible_labels, key=lambda row: (str(row.get("target_date")), str(row.get("market_id")))):
            event_slug = str(label["event_slug"])
            tape = Path(args.snapshots_root) / event_slug / "snapshots_long.csv"
            quick_state = _file_state(tape)
            prior_state = prior_tapes.get(event_slug) or {}
            settlement_revision = (
                label.get("revision_id")
                or label.get("label_hash")
                or f"sha256:compact:{_digest_payload(label)}"
            )
            unchanged = (
                args.command == "refresh"
                and quick_state.get("size_bytes") == prior_state.get("size_bytes")
                and quick_state.get("mtime_ns") == prior_state.get("mtime_ns")
                and settlement_revision == prior_state.get("settlement_revision")
            )
            if unchanged:
                tape_states[event_slug] = prior_state
                continue
            processed_slugs.add(event_slug)
            payloads, tape_state = _market_day_payloads(
                label, Path(args.snapshots_root), Path(args.repo_root), regime_cache
            )
            tape_states[event_slug] = {**tape_state, "settlement_revision": settlement_revision}
            candidates.extend(payloads)

        countable_slugs = {str(label["event_slug"]) for label in eligible_labels}
        known_slugs = set(labels)
        processed_slugs.update(
            record.get("event_slug")
            for record in current_market_days.values()
            if record.get("event_slug") in known_slugs - countable_slugs
        )
        candidate_keys = {_record_key(record) for record in candidates}
        for prior in list(current_market_days.values()):
            if prior.get("event_slug") not in processed_slugs:
                continue
            if prior.get("record_key") in candidate_keys:
                continue
            withdrawn = {
                key: value for key, value in prior.items()
                if key not in {
                    "schema_version", "revision_id", "revision_number", "recorded_at_utc",
                    "supersedes_revision_id", "previous_record_hash", "record_hash",
                    "source_fingerprint", "record_key",
                }
            }
            withdrawn.update({
                "status": "withdrawn_no_current_countable_support",
                "withdrawal_reason": (
                    "settlement is no longer promotion-countable or the current served tape "
                    "does not yield this prior regime/slice"
                ),
                "tool_logic_version": TOOL_LOGIC_VERSION,
            })
            candidates.append(withdrawn)

        appended_market_days, previous_hash = _append_revisions(
            history_path, candidates, current, previous_hash
        )
        for record in appended_market_days:
            if record.get("status") == "promotion_countable":
                current_market_days[record["record_key"]] = record
            else:
                current_market_days.pop(record["record_key"], None)
        current_market_days = {
            key: record for key, record in current_market_days.items()
            if record.get("event_slug") in countable_slugs
        }
        weekly_candidates = weekly_payloads(
            list(current_market_days.values()),
            replicates=args.replicates,
            base_seed=args.seed,
        )
        weekly_candidate_keys = {_record_key(record) for record in weekly_candidates}
        for prior in list(current.values()):
            if prior.get("record_type") != "weekly_skill_revision":
                continue
            if prior.get("record_key") in weekly_candidate_keys:
                continue
            withdrawn = {
                key: value for key, value in prior.items()
                if key not in {
                    "schema_version", "revision_id", "revision_number", "recorded_at_utc",
                    "supersedes_revision_id", "previous_record_hash", "record_hash",
                    "source_fingerprint", "record_key",
                }
            }
            withdrawn.update({
                "status": "withdrawn_no_current_countable_support",
                "withdrawal_reason": "no current promotion-countable market-day revisions remain",
                "tool_logic_version": TOOL_LOGIC_VERSION,
            })
            weekly_candidates.append(withdrawn)
        appended_weekly, previous_hash = _append_revisions(
            history_path, weekly_candidates, current, previous_hash
        )
        current_weekly = [
            row for row in current.values()
            if row.get("record_type") == "weekly_skill_revision"
            and row.get("status") == "weekly_equal_market_day_aggregate"
        ]
        controls = positive_controls(
            Path(args.floor_control_rows) if args.floor_control_rows else None,
            Path(args.cool_bias_control_rows) if args.cool_bias_control_rows else None,
            replicates=args.replicates,
            seed=args.seed,
            prior=(prior_summary or {}).get("positive_controls"),
        )
        summary = {
            "schema_version": SUMMARY_SCHEMA_VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "PASS" if controls.get("status") == "PASS" or allow_missing_controls else "BLOCK",
            "mode": args.command,
            "reservation_guard": reservation,
            "history_path": str(history_path),
            "report_path": str(report_path),
            "history_tail_record_hash": previous_hash,
            "history_record_count": len(existing_rows) + len(appended_market_days) + len(appended_weekly),
            "appended_market_day_revisions": len(appended_market_days),
            "appended_weekly_revisions": len(appended_weekly),
            "settlement_labels": labels,
            "ledger_states": ledger_states,
            "tape_states": tape_states,
            "current_market_days": current_market_days,
            "current_weekly": current_weekly,
            "positive_controls": controls,
            "method": {
                "admission": "promotion_countable only",
                "settlement_authority": "data/settlements/<market>/ledger.jsonl",
                "weekly_weighting": "equal market-day",
                "cluster": "crossed target_date x market_id",
                "artifact_regime_boundary_anchor": FLOOR_REGIME_ANCHOR,
                "replicates": args.replicates,
                "seed": args.seed,
            },
            "host_cost": {
                "elapsed_seconds": time.perf_counter() - started,
                "tapes_rehashed_and_scored": len({record.get("event_slug") for record in candidates}),
                "snapshot_bytes_rehashed": sum(
                    int(state.get("size_bytes") or 0)
                    for slug, state in tape_states.items()
                    if slug in {record.get("event_slug") for record in candidates}
                ),
                "design": "full read on explicit backfill; changed-ledger and changed-tape reads on refresh",
            },
        }
        write_json_atomic(summary_path, summary)
        write_text_atomic(report_path, _render_report(summary))
        return summary
    finally:
        release_writer_lock(lock)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("backfill", "refresh"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[4]))
        sub.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
        sub.add_argument("--settlement-root", default=str(DEFAULT_SETTLEMENT_ROOT))
        sub.add_argument("--history-path", default=str(DEFAULT_HISTORY_PATH))
        sub.add_argument("--summary-path", default=str(DEFAULT_SUMMARY_PATH))
        sub.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH))
        sub.add_argument("--reservation-path", default=str(DEFAULT_RESERVATION_PATH))
        sub.add_argument("--floor-control-rows")
        sub.add_argument("--cool-bias-control-rows")
        sub.add_argument(
            "--allow-missing-positive-controls",
            action="store_true",
            help="test/fixture escape hatch; production backfills must not use it",
        )
        sub.add_argument("--replicates", type=int, default=DEFAULT_REPLICATES)
        sub.add_argument("--seed", type=int, default=DEFAULT_SEED)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = run_tracker(args)
    print(json.dumps({
        "status": summary["status"],
        "mode": summary["mode"],
        "history_path": summary["history_path"],
        "report_path": summary["report_path"],
        "appended_market_day_revisions": summary["appended_market_day_revisions"],
        "appended_weekly_revisions": summary["appended_weekly_revisions"],
        "host_cost": summary["host_cost"],
    }, indent=2, sort_keys=True))
    return 0 if summary["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
