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

* the snapshot tape's SHA-256 (size and mtime only decide whether to re-hash;
  a byte-identical rewrite is reused);
* the daily-summary path and its normalized row for the folder's target date
  (a late WU correction changes that row and forces a re-finalize);
* the market spec (``repr`` of the registry entry plus its resolution spec);
* the resolved ledger root;
* the label-logic key: the source bytes of the modules that compute a label,
  the ledger schema version, the coverage interval and tolerance, and
  ``INCREMENTAL_FINALIZE_LOGIC_VERSION``;
* the folder's ``settlement.json`` still carries the revision this index
  recorded (no other finalize path has written it since);
* the ledger, which is the source of truth, agrees: its current revision for
  the slug is the sidecar's, and the sidecar's content hashes to the recorded
  ``label_hash`` (a truncated ledger or a hand-edited sidecar re-finalizes);
* the recorded reconciliation is terminal: ``match`` on a closed event with a
  matching winner that is UMA-resolved or priced at 0.999 or above;
* no manual override applies to the folder;
* the target date is older than the recheck window.

Under ``--label-rule venue`` (``venue_label_sources``) the same predicate
applies, with each folder's label source routed by
``market_day_labels.venue_label_plan``. A folder dated before the venue-rule
cutover is labelled from the WU daily summary exactly as under the WU rule, so
its key is the WU key and its reuse is unaffected by the rule. A folder dated
on or after the cutover is labelled from its market's venue-rule CSV, so its
daily-summary path is that CSV and its key gains a ``venue_label`` entry: the
SHA-256 of the CSV's whole target-date row (every provenance column, not only
the bucket), the rule version, the cutover date, the station-config hash (the
checked-in file and the one the CSV's manifest recorded), the ledger's
complete-day threshold and the source bytes of the venue label and routing
modules. Switching the rule therefore re-finalizes every post-cutover folder,
and a changed venue row re-finalizes exactly that folder. The venue refusals
(missing CSV, post-cutover date with no row or a thin row) are decided before
planning on every run and are never reused.

Anything else is re-finalized through the canonical path. ``--finalize-full``
forces the old behavior. Reused folders contribute their existing
``settlement.json`` label to the labels CSV and to the step summary, so the
CSV holds the same settlement content a full run would write. The only fields
that differ are those a full run rewrites on every pass without any input
changing: the revision metadata and ``finalized_at_utc`` (see
``VOLATILE_LABEL_COLUMNS``).
"""

from __future__ import annotations

import csv
import hashlib
import importlib
import json
from datetime import datetime, timedelta
from pathlib import Path

from weather.backtesting import settlement_ledger, venue_rule_labels
from weather.io import write_json_atomic
from weather.market import market_day_labels
from weather.market.market_config import date_from_event_slug
from weather.market.market_registry import spec_for_slug
from weather.model.model_constants import TORONTO_TZ


INCREMENTAL_FINALIZE_LOGIC_VERSION = 1
# The index is a disposable cache, not durable evidence: deleting it only costs
# one full pass, and every entry is re-proved against the folder before reuse.
# It is therefore versioned by a format name plus integer rather than through
# weather.schema_registry (whose data module sits in the capture loops' import
# closure, so registering it would make this change roll-sensitive).
FINALIZE_INDEX_FORMAT = "market_day_labels_finalize_index"
FINALIZE_INDEX_FORMAT_VERSION = 1
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

# Modules whose code decides a venue-rule label row or how a venue-mode folder
# is routed. They enter only the post-cutover venue key, so a change to them
# never re-finalizes a WU-labelled folder.
_VENUE_LOGIC_MODULES = (
    "weather.backtesting.venue_rule_labels",
    "weather.market.market_day_labels",
)


def _sha256_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(payload):
    return _sha256_bytes(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    )


def finalize_index_path(labels_csv):
    return Path(labels_csv).with_name(FINALIZE_INDEX_NAME)


def _module_digest(names, digest):
    for name in names:
        module = importlib.import_module(name)
        digest.update(name.encode("utf-8"))
        digest.update(Path(module.__file__).read_bytes())
    return digest


def label_logic_key(interval_minutes, gap_tolerance):
    digest = _module_digest(_LABEL_LOGIC_MODULES, hashlib.sha256())
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
    if (
        not isinstance(payload, dict)
        or payload.get("format") != FINALIZE_INDEX_FORMAT
        or payload.get("format_version") != FINALIZE_INDEX_FORMAT_VERSION
    ):
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
    """Return ``(sha256, stat)`` for the tape.

    Only the SHA-256 is compared; size and mtime are a fast path that skips
    re-hashing an untouched tape. A byte-identical rewrite (new mtime) is
    re-hashed, matches, and is reused.
    """

    stat = tape.stat()
    tape_stat = {"size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}
    previous = previous or {}
    prior_stat = previous.get("tape_stat") or {}
    prior_sha = (previous.get("key") or {}).get("tape_sha256")
    if prior_sha and prior_stat == tape_stat:
        return prior_sha, tape_stat
    return settlement_ledger.file_sha256(tape), tape_stat


class _SummaryCache:
    def __init__(self):
        self._by_path = {}

    def row(self, path, target_date):
        key = str(path)
        if key not in self._by_path:
            self._by_path[key] = settlement_ledger.load_daily_summary(path)
        iso = target_date.isoformat() if target_date else None
        return settlement_ledger.normalize_summary(self._by_path[key].get(iso))


class _LedgerCache:
    """Reads each market's ledger.jsonl once per planning pass."""

    def __init__(self, ledger_root):
        self.root = settlement_ledger.resolve_ledger_root(ledger_root)
        self._rows_by_market = {}

    def current(self, slug):
        spec = spec_for_slug(slug)
        if spec is None:
            return None
        if spec.id not in self._rows_by_market:
            self._rows_by_market[spec.id] = settlement_ledger.read_jsonl(
                settlement_ledger.ledger_path_for_market(spec.id, self.root)
            )
        return settlement_ledger.current_ledger_label(self._rows_by_market[spec.id], slug)


def folder_input_key(
    folder,
    *,
    daily_summary_path,
    overrides,
    logic_key,
    summaries,
    ledger_root,
    previous=None,
    label_rule_key=None,
):
    """Return ``(key, tape_stat, reason)``; ``key`` is None when the folder must not be reused."""

    folder = Path(folder)
    tape = folder / "snapshots_long.csv"
    if not tape.exists():
        return None, None, "no_tape"
    slug = folder.name
    spec = spec_for_slug(slug)
    target_date = date_from_event_slug(slug)
    if spec is None or target_date is None:
        return None, None, "unregistered_slug"
    if settlement_ledger.override_bucket(overrides or {}, spec, target_date, slug) is not None:
        return None, None, "override_applies"
    summary_path = (
        Path(daily_summary_path)
        if daily_summary_path
        else settlement_ledger.daily_summary_path_for_spec(spec)
    )
    tape_sha256, tape_stat = _tape_identity(tape, previous)
    key = {
        "logic_key": logic_key,
        "spec_sha256": _canonical(
            {"spec": repr(spec), "resolution": settlement_ledger.resolution_spec_for(spec)}
        ),
        "daily_summary_path": str(summary_path),
        "summary_row_sha256": _canonical(summaries.row(summary_path, target_date)),
        "ledger_root": str(settlement_ledger.resolve_ledger_root(ledger_root)),
        "tape_sha256": tape_sha256,
    }
    if label_rule_key is not None:
        # Only venue-labelled folders carry this entry, so a WU key (and every
        # index written before venue mode existed) is unchanged.
        key["venue_label"] = label_rule_key
    return key, tape_stat, None


def _reconciliation_terminal(label):
    """``match`` on a closed event whose matching winner is actually resolved.

    ``polymarket_winning_markets`` admits a winner on ``closed`` with a Yes
    price above 0.5, so a closed but unresolved event priced 0.6/0.4 can read
    as a ``match``. That is provisional and must be re-fetched.
    """

    reconciliation = label.get("polymarket_reconciliation") or {}
    if not (
        label.get("reconciliation_status") in TERMINAL_RECONCILIATION_STATUSES
        and reconciliation.get("event_closed") is True
    ):
        return False
    for market in reconciliation.get("matching_winning_markets") or []:
        if not isinstance(market, dict):
            continue
        yes_price = settlement_ledger.safe_float(market.get("yes_price"))
        if market.get("resolved") is True or (yes_price is not None and yes_price >= 0.999):
            return True
    return False


def _sidecar_matches_ledger(sidecar, current):
    """The sidecar is the current ledger revision, byte-for-byte in content.

    The ledger is the source of truth: the sidecar must carry the ledger's
    current revision id, and its label content must hash to both its own
    recorded ``label_hash`` and the ledger row's (a hand edit breaks either).
    """

    if current is None or current.get("revision_id") != sidecar.get("revision_id"):
        return False
    content_hash = settlement_ledger._canonical_sha256(settlement_ledger._label_payload(sidecar))
    return (
        content_hash == sidecar.get("label_hash")
        and content_hash == settlement_ledger._label_hash(current)
    )


def plan_incremental_finalize(
    folders,
    *,
    index,
    daily_summary_path,
    overrides,
    interval_minutes,
    gap_tolerance,
    ledger_root=None,
    recheck_days=DEFAULT_RECHECK_DAYS,
    today=None,
    force_full=False,
    label_sources=None,
):
    """Split ``folders`` into ``(to_finalize, reused, keys, reasons)``.

    ``label_sources`` (venue mode, from ``venue_label_sources``) maps each
    folder path to its ``daily_summary_path`` and ``label_rule_key``; without
    it every folder uses ``daily_summary_path`` and carries no rule key.

    ``reused`` maps folder path to its current ``settlement.json`` label.
    ``keys`` maps folder path to ``{"key", "tape_stat"}`` for every folder that
    has a key, computed before finalization so the index records the inputs
    the label was built from.
    """

    today = today or datetime.now(TORONTO_TZ).date()
    recheck_floor = today - timedelta(days=max(0, int(recheck_days)))
    logic_key = label_logic_key(interval_minutes, gap_tolerance)
    summaries = _SummaryCache()
    ledgers = _LedgerCache(ledger_root)
    to_finalize, reused, keys, reasons = [], {}, {}, {}
    for folder in folders:
        folder = Path(folder)
        previous = index.get(folder.name)
        source = (label_sources or {}).get(str(folder)) or {}
        key, tape_stat, reason = folder_input_key(
            folder,
            daily_summary_path=source.get("daily_summary_path", daily_summary_path),
            label_rule_key=source.get("label_rule_key"),
            overrides=overrides,
            logic_key=logic_key,
            summaries=summaries,
            ledger_root=ledger_root,
            previous=previous,
        )
        if key is not None:
            keys[str(folder)] = {"key": key, "tape_stat": tape_stat}
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
        if reason is None and not _sidecar_matches_ledger(sidecar, ledgers.current(folder.name)):
            reason = "ledger_disagrees"
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
        identity = keys.get(str(folder))
        if identity is None:
            continue
        key = identity["key"]
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
            "tape_stat": identity["tape_stat"],
            "revision_id": label.get("revision_id"),
            "label_hash": label.get("label_hash"),
        }
    return entries


def write_finalize_index(path, entries):
    write_json_atomic(
        path,
        {
            "format": FINALIZE_INDEX_FORMAT,
            "format_version": FINALIZE_INDEX_FORMAT_VERSION,
            "logic_version": INCREMENTAL_FINALIZE_LOGIC_VERSION,
            "folders": dict(sorted(entries.items())),
        },
    )


def _summary_groups(folders, label_sources, daily_summary_path):
    """``(daily_summary_path, folders)`` groups in first-seen order.

    Without ``label_sources`` this is the single original call, made even with
    no folders so the resolution specs are written as before.
    """

    if label_sources is None:
        return [(daily_summary_path, list(folders))]
    groups = {}
    for folder in folders:
        path = (label_sources.get(str(folder)) or {}).get("daily_summary_path")
        groups.setdefault(path, []).append(folder)
    return list(groups.items()) or [(daily_summary_path, [])]


class _VenueRowCache:
    """Each venue-rule CSV's raw rows by ``local_date``, read once per pass."""

    def __init__(self):
        self._by_path = {}

    def row_sha256(self, path, target_date):
        key = str(path)
        if key not in self._by_path:
            rows = {}
            with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    if row.get("local_date"):
                        rows[row["local_date"]] = row
            self._by_path[key] = rows
        row = self._by_path[key].get(target_date.isoformat())
        return _canonical(row) if row is not None else None


def _manifest_station_config_sha256(spec, venue_labels_root):
    path = venue_rule_labels.default_manifest_path(spec, venue_labels_root)
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return manifest.get("station_config_sha256") if isinstance(manifest, dict) else None


def venue_label_sources(folders, venue_labels_root, *, cutover=None, station_config_path=None):
    """Plan ``--label-rule venue`` inputs for ``finalize_incrementally``.

    Returns ``(planned, label_sources, refused)``. ``refused`` holds the
    ``(folder, reason)`` pairs ``market_day_labels.venue_label_plan`` refuses;
    they are re-decided on every run. ``planned`` is every other folder.
    ``label_sources`` maps each planned folder's path to its
    ``daily_summary_path`` (None, so the WU summary, before the cutover; the
    market's venue CSV from it) and ``label_rule_key`` (None before the
    cutover). Raises ``market_day_labels.VenueLabelsUnavailable`` when a
    market's CSV is missing.
    """

    cutover = cutover or venue_rule_labels.VENUE_RULE_CUTOVER_DATE
    station_config_path = station_config_path or venue_rule_labels.DEFAULT_STATION_CONFIG
    groups, refused = market_day_labels.venue_label_plan(folders, venue_labels_root, cutover=cutover)
    rule = {
        "label_rule": "venue",
        "label_rule_version": venue_rule_labels.VENUE_RULE_VERSION,
        "cutover_date": cutover.isoformat(),
        "station_config_sha256": settlement_ledger.file_sha256(station_config_path),
        "complete_day_min_rows": settlement_ledger.COMPLETE_DAY_MIN_ROWS,
        "venue_logic_sha256": _module_digest(_VENUE_LOGIC_MODULES, hashlib.sha256()).hexdigest(),
    }
    rows = _VenueRowCache()
    planned, sources = [], {}
    for name, path, group in groups:
        for folder in group:
            folder = Path(folder)
            planned.append(folder)
            if name == market_day_labels.WU_HISTORY_GROUP:
                sources[str(folder)] = {"daily_summary_path": None, "label_rule_key": None}
                continue
            target_date = date_from_event_slug(folder.name)
            sources[str(folder)] = {
                "daily_summary_path": str(path),
                "label_rule_key": dict(
                    rule,
                    venue_labels_csv=str(path),
                    manifest_station_config_sha256=_manifest_station_config_sha256(
                        spec_for_slug(folder.name), venue_labels_root
                    ),
                    venue_row_sha256=(
                        rows.row_sha256(path, target_date) if target_date is not None else None
                    ),
                ),
            }
    return planned, sources, refused


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
    label_sources=None,
    refused=(),
):
    """Finalize changed folders through the canonical path; reuse the rest.

    Always reconciles with Polymarket (incremental mode requires it). Returns
    ``(labels, plan)`` where ``labels`` covers every folder in the same way a
    full ``finalize_folders`` call would, and ``plan`` describes the split.
    On a per-folder failure the labels CSV is merged (as a full run would) and
    ``FolderFinalizationError`` is re-raised after the index is updated for
    the folders that did succeed.

    Venue mode passes ``label_sources`` and ``refused`` from
    ``venue_label_sources``: the folders to finalize are then finalized once
    per daily-summary path, and every refused ``(folder, reason)`` is reported
    as a failure (never finalized, never indexed) after the others are written,
    as ``market_day_labels.finalize_with_venue_labels`` does.
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
        ledger_root=ledger_root,
        recheck_days=recheck_days,
        today=today,
        force_full=force_full,
        label_sources=label_sources,
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
    if label_sources is not None:
        plan["label_rule"] = "venue"
        plan["refused_folder_count"] = len(refused)
    labels_csv.parent.mkdir(parents=True, exist_ok=True)
    scratch_csv = labels_csv.with_name(labels_csv.name + ".incremental.tmp")
    fresh, failures = [], list(refused)
    for summary_path, group in _summary_groups(to_finalize, label_sources, daily_summary_path):
        try:
            fresh.extend(
                finalize_folders(
                    group,
                    daily_summary_path=summary_path,
                    labels_csv=scratch_csv,
                    overrides=overrides,
                    interval_minutes=interval_minutes,
                    gap_tolerance=gap_tolerance,
                    reconcile_polymarket=True,
                    ledger_root=ledger_root,
                )
            )
        except settlement_ledger.FolderFinalizationError as exc:
            fresh.extend(exc.labels)
            failures.extend(exc.failures)
        finally:
            scratch_csv.unlink(missing_ok=True)
    failure = (
        settlement_ledger.FolderFinalizationError(failures, labels=fresh) if failures else None
    )
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
