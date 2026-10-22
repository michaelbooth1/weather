"""Incremental market-day label finalization for the daily refresh.

``market_day_labels_finalize`` used to rebuild every settled folder on every
run: one pandas tape parse, one per-folder daily-summary load, one ledger
read/verify and one Gamma ``GET`` per folder, and a fresh ``finalized_at_utc``
that appends a new ledger revision for every folder every day. That cost grows
with the corpus and ran Stage A into its 11:55 deadline.

This module decides, *before* calling the unchanged
``settlement_ledger.finalize_folders``, which folders a full run would
re-finalize to the same settlement content, and skips them. The settlement
logic itself is not touched (``settlement_ledger`` sits inside the capture
loops' import closure; this module and its caller do not).

A folder is reused only when every input that ``build_label`` reads is proved
unchanged against a per-folder entry in the finalize index written by an
earlier run of this step:

* the snapshot tape (size and mtime, falling back to SHA-256 on any change);
* the daily-summary path and its normalized row for the folder's target date
  (a late WU correction changes that row and forces a re-finalize);
* the market spec (``repr`` of the registry entry plus its resolution spec);
* the label-logic key: the source bytes of the modules that compute a label,
  the ledger schema version, the coverage interval and tolerance, and
  ``INCREMENTAL_FINALIZE_LOGIC_VERSION``;
* the folder's ``settlement.json`` still carries the revision this index
  recorded (no other finalize path has written it since);
* the recorded reconciliation is terminal: ``match`` on a closed event;
* no manual override applies to the folder;
* the target date is older than the recheck window.

Anything else is re-finalized through the canonical path. ``--finalize-full``
forces the old behavior. Reused folders contribute their existing
``settlement.json`` label to the labels CSV and to the step summary, so the
CSV holds the same settlement content a full run would write. The only fields
that differ are those a full run rewrites on every pass without any input
changing: the revision metadata and ``finalized_at_utc`` (see
``VOLATILE_LABEL_COLUMNS``).
"""

from __future__ import annotations

import hashlib
import importlib
import json
from datetime import datetime, timedelta
from pathlib import Path

from weather.backtesting import settlement_ledger
from weather.io import write_json_atomic
from weather.market.market_config import date_from_event_slug
from weather.market.market_registry import spec_for_slug
from weather.model.model_constants import TORONTO_TZ


INCREMENTAL_FINALIZE_LOGIC_VERSION = 1
FINALIZE_INDEX_SCHEMA = "market_day_labels_finalize_index_v1"
FINALIZE_INDEX_NAME = "market_day_labels_finalize_index.json"
DEFAULT_RECHECK_DAYS = 3
TERMINAL_RECONCILIATION_STATUSES = frozenset({"match"})

# Columns of the labels CSV that a full run rewrites on every pass even when no
# input changed. Every other column is settlement content and must be identical
# between a full and an incremental run.
VOLATILE_LABEL_COLUMNS = (
    "revision_id",
    "revision_number",
    "recorded_at_utc",
    "supersedes_revision_id",
    "previous_label_hash",
    "label_hash",
    "finalized_at_utc",
)

# Modules whose code decides label content. A change to any of them changes the
# logic key and re-finalizes every folder once.
_LABEL_LOGIC_MODULES = (
    "weather.backtesting.settlement_ledger",
    "weather.collection.collection_health",
    "weather.market.market_config",
    "weather.market.market_registry",
    "weather.units",
)


def _sha256_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(payload):
    return _sha256_bytes(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    )


def finalize_index_path(labels_csv):
    return Path(labels_csv).with_name(FINALIZE_INDEX_NAME)


def label_logic_key(interval_minutes, gap_tolerance):
    digest = hashlib.sha256()
    for name in _LABEL_LOGIC_MODULES:
        module = importlib.import_module(name)
        digest.update(name.encode("utf-8"))
        digest.update(Path(module.__file__).read_bytes())
    digest.update(
        json.dumps(
            {
                "ledger_schema": settlement_ledger.LEDGER_SCHEMA_VERSION,
                "interval_minutes": float(interval_minutes),
                "gap_tolerance": float(gap_tolerance),
                "logic_version": INCREMENTAL_FINALIZE_LOGIC_VERSION,
            },
            sort_keys=True,
        ).encode("utf-8")
    )
    return digest.hexdigest()


def read_finalize_index(path):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict) or payload.get("schema") != FINALIZE_INDEX_SCHEMA:
        return {}
    folders = payload.get("folders")
    return folders if isinstance(folders, dict) else {}


def _read_sidecar(folder):
    try:
        payload = json.loads((Path(folder) / "settlement.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _tape_identity(tape, previous):
    stat = tape.stat()
    identity = {"size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}
    prior = (previous or {}).get("tape") or {}
    if (
        prior.get("size") == identity["size"]
        and prior.get("mtime_ns") == identity["mtime_ns"]
        and prior.get("sha256")
    ):
        identity["sha256"] = prior["sha256"]
    else:
        identity["sha256"] = settlement_ledger.file_sha256(tape)
    return identity


class _SummaryCache:
    def __init__(self):
        self._by_path = {}

    def row(self, path, target_date):
        key = str(path)
        if key not in self._by_path:
            self._by_path[key] = settlement_ledger.load_daily_summary(path)
        iso = target_date.isoformat() if target_date else None
        return settlement_ledger.normalize_summary(self._by_path[key].get(iso))


def folder_input_key(folder, *, daily_summary_path, overrides, logic_key, summaries, previous=None):
    """Return ``(key, reason)``; ``key`` is None when the folder must not be reused."""

    folder = Path(folder)
    tape = folder / "snapshots_long.csv"
    if not tape.exists():
        return None, "no_tape"
    slug = folder.name
    spec = spec_for_slug(slug)
    target_date = date_from_event_slug(slug)
    if spec is None or target_date is None:
        return None, "unregistered_slug"
    if settlement_ledger.override_bucket(overrides or {}, spec, target_date, slug) is not None:
        return None, "override_applies"
    summary_path = (
        Path(daily_summary_path)
        if daily_summary_path
        else settlement_ledger.daily_summary_path_for_spec(spec)
    )
    key = {
        "logic_key": logic_key,
        "spec_sha256": _canonical(
            {"spec": repr(spec), "resolution": settlement_ledger.resolution_spec_for(spec)}
        ),
        "daily_summary_path": str(summary_path),
        "summary_row_sha256": _canonical(summaries.row(summary_path, target_date)),
        "tape": _tape_identity(tape, previous),
    }
    return key, None


def _reconciliation_terminal(label):
    reconciliation = label.get("polymarket_reconciliation") or {}
    return bool(
        label.get("reconciliation_status") in TERMINAL_RECONCILIATION_STATUSES
        and reconciliation.get("event_closed") is True
    )


def plan_incremental_finalize(
    folders,
    *,
    index,
    daily_summary_path,
    overrides,
    interval_minutes,
    gap_tolerance,
    recheck_days=DEFAULT_RECHECK_DAYS,
    today=None,
    force_full=False,
):
    """Split ``folders`` into ``(to_finalize, reused, keys, reasons)``.

    ``reused`` maps folder path to its current ``settlement.json`` label.
    ``keys`` holds the input key of every folder that has one, computed before
    finalization so the index records the inputs the label was built from.
    """

    today = today or datetime.now(TORONTO_TZ).date()
    recheck_floor = today - timedelta(days=max(0, int(recheck_days)))
    logic_key = label_logic_key(interval_minutes, gap_tolerance)
    summaries = _SummaryCache()
    to_finalize, reused, keys, reasons = [], {}, {}, {}
    for folder in folders:
        folder = Path(folder)
        previous = index.get(folder.name)
        key, reason = folder_input_key(
            folder,
            daily_summary_path=daily_summary_path,
            overrides=overrides,
            logic_key=logic_key,
            summaries=summaries,
            previous=previous,
        )
        if key is not None:
            keys[str(folder)] = key
        target_date = date_from_event_slug(folder.name)
        sidecar = _read_sidecar(folder)
        if reason is None and force_full:
            reason = "forced_full"
        if reason is None and target_date is not None and target_date >= recheck_floor:
            reason = "inside_recheck_window"
        if reason is None and not previous:
            reason = "not_indexed"
        if reason is None and previous.get("key") != key:
            reason = "inputs_changed"
        if reason is None and sidecar is None:
            reason = "sidecar_missing"
        if reason is None and (
            sidecar.get("revision_id") != previous.get("revision_id")
            or sidecar.get("label_hash") != previous.get("label_hash")
        ):
            reason = "sidecar_revision_changed"
        if reason is None and not _reconciliation_terminal(sidecar):
            reason = "reconciliation_not_terminal"
        if reason is None:
            reused[str(folder)] = sidecar
        else:
            reasons[reason] = reasons.get(reason, 0) + 1
            to_finalize.append(folder)
    return to_finalize, reused, keys, reasons


def build_finalize_index(folders, *, keys, labels_by_slug, reused, previous_index):
    """Index entries for every folder whose current label is known to be good."""

    entries = {}
    for folder in folders:
        folder = Path(folder)
        key = keys.get(str(folder))
        if key is None:
            continue
        label = labels_by_slug.get(folder.name)
        if label is None and str(folder) in reused:
            label = reused[str(folder)]
            prior = previous_index.get(folder.name) or {}
            if prior.get("key") != key:
                continue
        if label is None:
            continue
        entries[folder.name] = {
            "key": key,
            "revision_id": label.get("revision_id"),
            "label_hash": label.get("label_hash"),
        }
    return entries


def write_finalize_index(path, entries):
    write_json_atomic(
        path,
        {
            "schema": FINALIZE_INDEX_SCHEMA,
            "logic_version": INCREMENTAL_FINALIZE_LOGIC_VERSION,
            "folders": dict(sorted(entries.items())),
        },
    )


def finalize_incrementally(
    folders,
    *,
    daily_summary_path,
    labels_csv,
    overrides,
    interval_minutes,
    gap_tolerance,
    ledger_root,
    recheck_days=DEFAULT_RECHECK_DAYS,
    today=None,
    force_full=False,
    finalize_folders=None,
):
    """Finalize changed folders through the canonical path; reuse the rest.

    Always reconciles with Polymarket (incremental mode requires it). Returns
    ``(labels, plan)`` where ``labels`` covers every folder in the same way a
    full ``finalize_folders`` call would, and ``plan`` describes the split.
    On a per-folder failure the labels CSV is merged (as a full run would) and
    ``FolderFinalizationError`` is re-raised after the index is updated for
    the folders that did succeed.
    """

    finalize_folders = finalize_folders or settlement_ledger.finalize_folders
    folders = [Path(folder) for folder in folders]
    labels_csv = Path(labels_csv)
    index_path = finalize_index_path(labels_csv)
    previous_index = read_finalize_index(index_path)
    to_finalize, reused, keys, reasons = plan_incremental_finalize(
        folders,
        index=previous_index,
        daily_summary_path=daily_summary_path,
        overrides=overrides,
        interval_minutes=interval_minutes,
        gap_tolerance=gap_tolerance,
        recheck_days=recheck_days,
        today=today,
        force_full=force_full,
    )
    plan = {
        "mode": "full" if force_full else "incremental",
        "folder_count": len(folders),
        "finalized_folder_count": len(to_finalize),
        "reused_folder_count": len(reused),
        "refinalize_reasons": dict(sorted(reasons.items())),
        "recheck_days": int(recheck_days),
        "index_path": str(index_path),
    }
    labels_csv.parent.mkdir(parents=True, exist_ok=True)
    scratch_csv = labels_csv.with_name(labels_csv.name + ".incremental.tmp")
    failure = None
    try:
        try:
            fresh = finalize_folders(
                to_finalize,
                daily_summary_path=daily_summary_path,
                labels_csv=scratch_csv,
                overrides=overrides,
                interval_minutes=interval_minutes,
                gap_tolerance=gap_tolerance,
                reconcile_polymarket=True,
                ledger_root=ledger_root,
            )
        except settlement_ledger.FolderFinalizationError as exc:
            failure = exc
            fresh = list(exc.labels)
    finally:
        scratch_csv.unlink(missing_ok=True)
    fresh_by_slug = {label.get("event_slug"): label for label in fresh if label}
    combined = list(fresh) + [
        label for label in reused.values() if label.get("event_slug") not in fresh_by_slug
    ]
    if failure is not None:
        settlement_ledger.merge_labels_csv(labels_csv, combined)
    else:
        settlement_ledger.write_labels_csv(labels_csv, combined)
    entries = build_finalize_index(
        folders,
        keys=keys,
        labels_by_slug=fresh_by_slug,
        reused=reused,
        previous_index=previous_index,
    )
    write_finalize_index(index_path, entries)
    plan["indexed_folder_count"] = len(entries)
    if failure is not None:
        raise failure
    return combined, plan

