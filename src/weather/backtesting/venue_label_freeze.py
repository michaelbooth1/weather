"""Look-morning label freeze, atomic, with a named recovery (R24; master rulings 2026-11-03, items 2(a)-(c)).

``python -m weather.backtesting.venue_label_audit freeze`` calls this module, which was split out of
``venue_label_audit`` to keep that module inside its line budget.

* ``freeze(look, through)`` refreshes (``venue_label_audit.refresh``), then:
  - **(a)** refuses before any folder under ``frozen/`` is made unless the run's counts-only audit status is
    ``OK`` (``STATION_DRIFT`` exits 3). Nothing is frozen, and master rules the drift outcome-blind;
  - refuses a build manifest without its key lists (``label_dates``, ``skipped_dates``), also before any folder;
  - **(b)** copies each market's CSV, manifest and WU daily summary into
    ``frozen/<look>.tmp-<utc>-<pid>/`` with ``freeze_receipt.json``. It re-reads that receipt and re-hashes
    every file. It renames the folder to ``frozen/<look>`` only when every sha is present, equals the bytes,
    and the CSV and WU summary match their manifest. A crash or a failed check leaves only the tmp folder: a
    later freeze reports it (``ignored_partial_dirs``) and ignores it, and ``frozen/<look>`` never exists
    half-written.
* ``recover(look, ruling)`` (**(c)**, ``freeze --recover <look> --ruling <file>``) moves a defective
  ``frozen/<look>`` (no readable receipt, or a null sha) to ``frozen/<look>.void-<utc>`` and writes a
  ``venue_label_freeze_recovery_v1`` record into it. It runs only when no look stamp or receipt for that look
  exists (``LOOK_STAMPS``; an unregistered look id is refused). It needs master's dated, outcome-blind ruling
  file (``venue_label_freeze_recovery_ruling_v1``: ``schema_version``, ``dated``, ``outcome_blind: true``,
  ``look_id``, ``reason``). Nothing is deleted. A re-freeze after it is outcome-blind, because the freeze
  copies bytes and reads no label value.

Embargo as ``venue_label_audit``: this module never imports the label reader, never opens the reserved window,
and never writes a label value, bucket or winner.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

from weather.backtesting import venue_label_audit as audit
from weather.backtesting.venue_rule_labels import DEFAULT_LABEL_ROOT, default_label_path, default_manifest_path
from weather.market.market_registry import BUILTIN_SPECS
from weather.paths import DATA_ROOT
from weather.schema_families import schema_version

RECEIPT_NAME = "freeze_receipt.json"
RECOVERY_NAME = "recovery_record.json"
RULING_SCHEMA = schema_version("venue_label_freeze_recovery_ruling")
RECOVERY_SCHEMA = schema_version("venue_label_freeze_recovery")
FROZEN_FILES = ("label_csv", "manifest", "wu_daily_summary")
# Look id -> (folder under data/, the stamp and receipt globs of that look). A recovery is refused while any exists.
LOOK_STAMPS = {
    "mg1": ("mg1_look", ("started-*.json", "receipt-*.json")),  # weather.calibration.mg1_look
    "b": ("b_look", ("consumed-*.json",)),  # weather.calibration.b_scorer consumed marker
}


class FreezeDrift(audit.AuditRefused):
    """The run's counts-only audit is not OK: nothing was frozen."""

    exit_code = audit.EXIT_STATION_DRIFT


def _stamp(now):
    return now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _look_dir(label_root, look_id):
    if not audit._LOOK_ID.match(str(look_id)):
        raise audit.AuditRefused(f"--look {look_id!r} must match {audit._LOOK_ID.pattern}")
    return Path(label_root) / audit.FROZEN_DIRNAME / look_id


def partial_dirs(label_root, look_id):
    """Left-over ``<look>.tmp-*`` folders of crashed or refused freezes (reported, never read)."""
    frozen = Path(label_root) / audit.FROZEN_DIRNAME
    return sorted(str(p) for p in frozen.glob(f"{look_id}.tmp-*") if p.is_dir())


def receipt_defects(look_dir):
    """Why a frozen folder is not a complete freeze: [] when its receipt is readable and every sha is present."""
    path = Path(look_dir) / RECEIPT_NAME
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
        markets = receipt["markets"]
    except (OSError, ValueError, KeyError, TypeError):
        return [f"no readable {RECEIPT_NAME}"]
    return [f"{market} {name} sha256 is null" for market, entry in sorted(markets.items()) for name in FROZEN_FILES
            if not (entry.get(name) or {}).get("sha256")]


def _verify(tmp, look_dir, written):
    """Re-read the receipt in ``tmp``; every recorded file must exist there with its sha and match its manifest."""
    if json.loads((tmp / RECEIPT_NAME).read_text(encoding="utf-8")) != written:
        return ["the receipt on disk differs from the receipt written"]
    problems = []
    for market, entry in sorted(written["markets"].items()):
        for name in FROZEN_FILES:
            want = entry[name].get("sha256")
            local = tmp / Path(entry[name]["path"]).relative_to(look_dir)
            if not want or not local.is_file() or audit._sha256(local) != want:
                problems.append(f"{market} {name} is missing or differs from its recorded sha256")
        if not (entry["label_csv_matches_manifest"] and entry["wu_daily_summary_matches_manifest"]):
            problems.append(f"{market} frozen files do not match their manifest")
    return problems


def freeze(look_id, through, *, label_root=DEFAULT_LABEL_ROOT, now=None, **refresh_kwargs):
    """Refresh, refuse unless OK, then build ``frozen/<look>`` atomically; returns ``(look_dir, receipt, audit)``."""
    look_dir = _look_dir(label_root, look_id)
    if look_dir.exists():
        raise audit.AuditRefused(f"{look_dir} exists: a look is frozen once")
    ignored = partial_dirs(label_root, look_id)
    run_dir, receipt, run_audit = audit.refresh(through, label_root=label_root, now=now, **refresh_kwargs)
    if run_audit["status"] != "OK":
        raise FreezeDrift(f"run {receipt['run_id']} audit status is {run_audit['status']}: nothing was frozen; rule it "
                          f"outcome-blind ({run_dir / 'audit.json'}) and freeze again")
    labels = run_dir / audit.LABELS_DIRNAME
    manifests = {spec.id: json.loads(default_manifest_path(spec, labels).read_text(encoding="utf-8"))
                 for spec in BUILTIN_SPECS}
    for market_id, manifest in manifests.items():  # key lists come from the manifest only, never the CSV
        for name in audit.FREEZE_KEY_FIELDS:
            if name not in manifest:
                raise audit.AuditRefused(f"the {market_id} build manifest has no {name}: rebuild the labels")
    started = now or datetime.now(timezone.utc)
    tmp = look_dir.parent / f"{look_id}.tmp-{_stamp(started)}-{os.getpid()}"
    tmp.mkdir(parents=True)
    markets = {}
    for spec in BUILTIN_SPECS:
        manifest = manifests[spec.id]
        copies = {
            "label_csv": (default_label_path(spec, labels), default_label_path(spec, look_dir)),
            "manifest": (default_manifest_path(spec, labels), default_manifest_path(spec, look_dir)),
            "wu_daily_summary": (Path(manifest["wu_daily_summary"]), look_dir / spec.id / "wu" / "daily_summary.csv"),
        }
        entry = {}
        for name, (source, target) in copies.items():
            if not source.is_file():
                entry[name] = {"path": str(target), "sha256": None, "missing_source": str(source)}
                continue
            local = tmp / target.relative_to(look_dir)
            local.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, local)
            entry[name] = {"path": str(target), "sha256": audit._sha256(local), "source": str(source)}
        entry["label_csv_matches_manifest"] = entry["label_csv"]["sha256"] == manifest.get("output_sha256")
        entry["wu_daily_summary_matches_manifest"] = (
            entry["wu_daily_summary"]["sha256"] == manifest.get("wu_daily_summary_sha256"))
        entry["label_dates"] = sorted(str(day) for day in manifest["label_dates"])  # keys only
        entry["skipped_dates"] = {str(day): str(reason) for day, reason in sorted(manifest["skipped_dates"].items())}
        markets[spec.id] = entry
    freeze_receipt = {
        "schema_version": audit.FREEZE_RECEIPT_SCHEMA,
        "look_id": look_id,
        "run_id": receipt["run_id"],
        "refresh_receipt_sha256": audit._sha256(run_dir / "refresh_receipt.json"),
        "audit_sha256": audit._sha256(run_dir / "audit.json"),
        "audit_status": run_audit["status"],
        "through": receipt["through"],
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "label_root": str(look_dir),
        "ignored_partial_dirs": ignored,
        "markets": markets,
    }
    audit._write_json(tmp / RECEIPT_NAME, freeze_receipt)
    problems = _verify(tmp, look_dir, freeze_receipt)
    if problems:
        raise audit.AuditRefused(f"the freeze in {tmp} failed its check, so frozen/{look_id} was not made (the tmp "
                                 f"folder is kept and ignored): {'; '.join(problems)}")
    tmp.rename(look_dir)
    return look_dir, freeze_receipt, run_audit


def read_ruling(path, look_id, today):
    """Master's dated, outcome-blind recovery ruling for ``look_id``; returns its sha256 or refuses."""
    p = Path(path)
    try:
        body = json.loads(p.read_text(encoding="utf-8"))
        dated = date.fromisoformat(str(body["dated"]))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise audit.AuditRefused(f"the recovery ruling {p} is missing or malformed: {exc}") from exc
    if body.get("schema_version") != RULING_SCHEMA:
        raise audit.AuditRefused(f"the recovery ruling schema is {body.get('schema_version')!r}, not {RULING_SCHEMA}")
    if body.get("outcome_blind") is not True:
        raise audit.AuditRefused("the recovery ruling is not marked outcome_blind")
    if body.get("look_id") != look_id:
        raise audit.AuditRefused(f"the recovery ruling names look {body.get('look_id')!r}, not {look_id!r}")
    if not str(body.get("reason") or "").strip():
        raise audit.AuditRefused("the recovery ruling gives no reason")
    if dated > today:
        raise audit.AuditRefused(f"the recovery ruling is dated {dated}, after today {today}")
    return audit._sha256(p)


def look_stamps(look_id, data_root=DATA_ROOT):
    """Every stamp or receipt the look has written; refuses a look id with no registered stamp location."""
    if look_id not in LOOK_STAMPS:
        raise audit.AuditRefused(f"look {look_id!r} has no registered stamp location (LOOK_STAMPS): recovery is "
                                 "refused")
    folder, globs = LOOK_STAMPS[look_id]
    root = Path(data_root) / folder
    return sorted(str(p) for pattern in globs for p in root.glob(pattern))


def recover(look_id, ruling, *, label_root=DEFAULT_LABEL_ROOT, data_root=DATA_ROOT, now=None):
    """Move a receipt-less or null-sha ``frozen/<look>`` to ``frozen/<look>.void-<utc>``; returns the record."""
    now = now or datetime.now(timezone.utc)
    look_dir = _look_dir(label_root, look_id)
    if not look_dir.is_dir():
        raise audit.AuditRefused(f"{look_dir} does not exist: there is nothing to recover")
    stamps = look_stamps(look_id, data_root)
    if stamps:
        raise audit.AuditRefused(f"look {look_id!r} has a stamp or receipt ({stamps[0]}): its freeze is never moved")
    defects = receipt_defects(look_dir)
    if not defects:
        raise audit.AuditRefused(f"{look_dir} is a complete freeze: recovery moves only a receipt-less or null-sha one")
    ruling_sha = read_ruling(ruling, look_id, now.date())
    void = look_dir.parent / f"{look_id}.void-{_stamp(now)}"
    if void.exists():
        raise audit.AuditRefused(f"{void} exists")
    look_dir.rename(void)
    record = {"schema_version": RECOVERY_SCHEMA, "look_id": look_id, "from": str(look_dir), "to": str(void),
              "defects": defects, "ruling": {"path": str(Path(ruling)), "sha256": ruling_sha},
              "recovered_at_utc": now.astimezone(timezone.utc).isoformat()}
    with open(void / RECOVERY_NAME, "x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return record
