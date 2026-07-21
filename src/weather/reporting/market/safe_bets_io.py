"""Bounded local-artifact loading for the safest-bets view model."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

from weather.io import read_pretty_json_top_level_values

from .safe_bets import (
    DEFAULT_LIMIT,
    DEFAULT_MIN_CONSERVATIVE_PROBABILITY,
    DEFAULT_MIN_INDEPENDENT_DAYS,
    DEFAULT_PERMISSION_MAP_PATH,
    DEFAULT_PERMISSION_MAX_AGE_SECONDS,
    DEFAULT_RUNS_ROOT,
    DEFAULT_RUN_MAX_AGE_SECONDS,
    _now_utc,
    _result,
    _target_date,
    build_safe_bets_payload,
)


_RUN_FIELDS = (
    "schema_version",
    "generated_at_utc",
    "run_id",
    "target_date",
    "mode",
    "experiment_id",
    "summary",
    "config",
    "strategies",
    "pnl",
    "latest_orders",
    "tape_integrity",
    "upstream_dependency_status",
    "exchange_economics_gate",
    "exchange_economics_snapshot_id",
    "exchange_economics_hash",
    "release_id",
    "release_manifest_sha256",
    "release_pointer_sha256",
    "release_sequence",
    "release_identity_status",
    "release_identity_reason",
    "base_model_release_bound",
    "base_model_binding_reason",
    "release_kind",
    "release_candidate_mode",
    "release_production_capable",
)
_PERMISSION_FIELDS = (
    "schema_version",
    "generated_at_utc",
    "summary",
    "records",
)


def _has_complete_pretty_json_envelope(path: Path, size: int) -> bool:
    """Prove the canonical pretty-JSON root opened and closed in column zero."""

    if size <= 0:
        return False
    try:
        with path.open("rb") as handle:
            head = handle.read(min(size, 4096))
            handle.seek(max(0, size - 64 * 1024))
            tail = handle.read(64 * 1024)
    except OSError:
        return False
    first_line = next((line for line in head.splitlines() if line.strip()), b"")
    last_line = next((line for line in reversed(tail.splitlines()) if line.strip()), b"")
    return first_line == b"{" and last_line == b"}"


def _stable_bounded_read(
    path: Path,
    fields: tuple[str, ...],
) -> dict[str, Any] | None:
    try:
        before = path.stat()
    except OSError:
        return None
    if not _has_complete_pretty_json_envelope(path, before.st_size):
        return None
    try:
        payload = read_pretty_json_top_level_values(path, fields)
    except (OSError, UnicodeError, ValueError):
        return None
    try:
        after = path.stat()
    except OSError:
        return None
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        return None
    return payload


def _newest_current_run(runs_root: Path, target_date: str) -> tuple[Path | None, bool]:
    date_root = runs_root / target_date
    try:
        children = list(date_root.iterdir())
    except OSError:
        return None, False
    candidates: list[tuple[int, str, Path]] = []
    for child in children:
        # Daily production run IDs are created by ``default_run_id`` with this
        # prefix. Housekeeping trees such as ``_quarantine`` must not look like
        # a newer half-copied run and suppress a healthy current summary.
        if not child.is_dir() or not child.name.startswith("taker-"):
            continue
        path = child / "run_summary.json"
        try:
            child_mtime = child.stat().st_mtime_ns
        except OSError:
            continue
        try:
            candidate_mtime = path.stat().st_mtime_ns if path.is_file() else child_mtime
        except OSError:
            candidate_mtime = child_mtime
        candidates.append((candidate_mtime, child.as_posix(), path))
    if not candidates:
        return None, False
    return max(candidates)[2], True


def load_safe_bets_payload(
    *,
    now: datetime | None = None,
    target_date: str | date | datetime | None = None,
    runs_root: str | Path | None = None,
    permission_map_path: str | Path | None = None,
    run_max_age_seconds: float = DEFAULT_RUN_MAX_AGE_SECONDS,
    permission_max_age_seconds: float = DEFAULT_PERMISSION_MAX_AGE_SECONDS,
    min_conservative_probability: float = DEFAULT_MIN_CONSERVATIVE_PROBABILITY,
    min_independent_days: int = DEFAULT_MIN_INDEPENDENT_DAYS,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Load the newest current-day paper run without older-run fallback."""

    now_utc = _now_utc(now)
    target = _target_date(target_date, now_utc)
    root = Path(runs_root) if runs_root is not None else DEFAULT_RUNS_ROOT
    permission_path = (
        Path(permission_map_path)
        if permission_map_path is not None
        else DEFAULT_PERMISSION_MAP_PATH
    )
    run_path, run_child_present = _newest_current_run(root, target)
    if run_path is None and not run_child_present:
        return _result(
            target,
            now_utc,
            "NO_DATA",
            "No current paper-taker run is available yet.",
            provenance={
                "runs_root": str(root),
                "permission_map_path": str(permission_path),
            },
        )

    run = _stable_bounded_read(run_path, _RUN_FIELDS)
    if not isinstance(run, Mapping) or not all(
        key in run
        for key in (
            "schema_version",
            "generated_at_utc",
            "run_id",
            "target_date",
            "mode",
            "summary",
            "config",
            "strategies",
            "latest_orders",
            "tape_integrity",
            "upstream_dependency_status",
            "exchange_economics_gate",
        )
    ):
        return _result(
            target,
            now_utc,
            "LOADING",
            "The newest paper run is incomplete while local data is syncing.",
            run_blockers=["run_artifact_incomplete"],
            provenance={"run_path": str(run_path)},
        )

    if not permission_path.is_file():
        return _result(
            target,
            now_utc,
            "BLOCKED",
            "The local settlement permission map is unavailable.",
            run_blockers=["permission_map_missing"],
            provenance={
                "run_path": str(run_path),
                "permission_map_path": str(permission_path),
            },
        )
    permission = _stable_bounded_read(permission_path, _PERMISSION_FIELDS)
    if not isinstance(permission, Mapping) or not all(
        key in permission for key in _PERMISSION_FIELDS
    ):
        return _result(
            target,
            now_utc,
            "LOADING",
            "The settlement permission map is incomplete while local data is syncing.",
            run_blockers=["permission_map_incomplete"],
            provenance={
                "run_path": str(run_path),
                "permission_map_path": str(permission_path),
            },
        )
    return build_safe_bets_payload(
        run,
        permission,
        now=now_utc,
        target_date=target,
        run_path=run_path,
        permission_map_path=permission_path,
        run_max_age_seconds=run_max_age_seconds,
        permission_max_age_seconds=permission_max_age_seconds,
        min_conservative_probability=min_conservative_probability,
        min_independent_days=min_independent_days,
        limit=limit,
    )


__all__ = ["load_safe_bets_payload"]
