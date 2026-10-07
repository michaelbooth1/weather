"""The bundle transfer manifest: capture-host build, workstation verify (maker replay v2 W7; reg §8).

Owner decision 19 (A-defender M9): the committed manifest lives at ``TRANSFER_MANIFEST_PATH`` and is
keyed **per bundle**, by ``(day, export_kind)``, because a calibration date carries two bundles (the
night-format export P1 and the calibration-kind export P2). ``export_kind`` is one of:

========================  ==========================  =======================
export_kind               day set (``panel``)         ``receipt.kind``
========================  ==========================  =======================
``panel_night``           ``QUOTE_DATES``             ``panel``
``settlement_night``      ``SETTLEMENT_ONLY_DATES``   ``panel``
``calibration_night``     ``CALIBRATION_DATES``       ``panel``
``calibration_hazard``    ``CALIBRATION_DATES``       ``calibration``
========================  ==========================  =======================

A root is one exported day folder as ``maker_replay_night_v02`` writes it: ``<root>/receipt.json`` and
``<root>/bundle/`` (``bundle.json`` plus one stream per kind).

- ``build(roots, *, host_id, created_at)`` runs on the capture host and reads only ``bundle.json`` and
  ``receipt.json`` under the manifest cap. Stream digests come from ``bundle.json`` and must equal the
  receipt's file digests; no stream byte is read.
- ``verify(doc, roots)`` runs on the workstation. Before any record is parsed it compares the raw
  ``bundle.json`` and ``receipt.json`` hashes, then runs the stream reader's pass one
  (``open_stream_bundle``: every stream hashed, sized and counted) and compares every field. It refuses
  ``transfer_manifest_mismatch:<day>:<field>``, a root whose ``(day, export_kind)`` is not listed
  (``transfer_manifest_unlisted:<day>:<export_kind>``) and a duplicate root. It returns the opened
  bundles; nothing has called ``records()``.

O9 (bundle transfer to the workstation) is on HOLD: this module is code and fictional tests only.
"""
from __future__ import annotations

from datetime import date
import json
import re
import time

from maker_core.replay.bundle import MAX_MANIFEST_BYTES, BundleError, Limits, _Reader, regular_path, sha256
from maker_core.replay.bundle_v02 import FORMAT_V02, open_stream_bundle
from maker_core.replay.v2 import panel as constants

FORMAT = "maker_core.replay.v2.transfer.v0.1"
TRANSFER_MANIFEST_PATH = "config/maker_replay_v2/transfer_manifest.json"
MAX_RECEIPT_BYTES = 4 * 1024**2
MAX_BUNDLES = 32
EXPORT_KINDS = ("panel_night", "settlement_night", "calibration_night", "calibration_hazard")
RECEIPT_KIND = dict(panel_night="panel", settlement_night="panel", calibration_night="panel",
                    calibration_hazard="calibration")
ENTRY_FIELDS = frozenset({"day", "export_kind", "format", "bundle_json_sha256", "receipt_sha256", "module_sha256",
                          "v01_equivalent_sha256", "streams"})
STREAM_FIELDS = frozenset({"sha256", "bytes", "records"})
DOC_FIELDS = frozenset({"format", "bundles", "host_id", "created_at"})
REFUSAL_CODES = ("transfer_root_invalid", "transfer_export_kind_unknown", "transfer_day_not_in_export_kind",
                 "transfer_receipt_not_sealed", "transfer_receipt_kind_mismatch", "transfer_receipt_day_mismatch",
                 "transfer_bundle_day_mismatch", "transfer_bundle_not_v02", "transfer_receipt_bundle_mismatch",
                 "transfer_duplicate_bundle", "transfer_manifest_invalid", "transfer_manifest_unlisted",
                 "transfer_manifest_mismatch")


def days_of(export_kind):
    if export_kind in ("panel_night",):
        return tuple(constants.QUOTE_DATES)
    if export_kind == "settlement_night":
        return tuple(constants.SETTLEMENT_ONLY_DATES)
    if export_kind in ("calibration_night", "calibration_hazard"):
        return tuple(constants.CALIBRATION_DATES)
    raise BundleError("transfer_export_kind_unknown")


def _read(path, cap):
    raw = _Reader(Limits(cap, 1, 30), time.monotonic).read(regular_path(path), cap)
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise BundleError("transfer_root_invalid") from exc
    if not isinstance(value, dict):
        raise BundleError("transfer_root_invalid")
    return value, sha256(raw)


def _day(value):
    try:
        day = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise BundleError("transfer_root_invalid") from exc
    if day.isoformat() != value:
        raise BundleError("transfer_root_invalid")
    return day


def _entry(export_kind, root):
    """One root's entry from ``bundle.json`` and ``receipt.json`` only."""
    if export_kind not in EXPORT_KINDS:
        raise BundleError("transfer_export_kind_unknown")
    root = regular_path(root)
    receipt, receipt_hash = _read(root / "receipt.json", MAX_RECEIPT_BYTES)
    manifest, manifest_hash = _read(root / "bundle" / "bundle.json", MAX_MANIFEST_BYTES)
    day = _day(manifest.get("day"))
    if day not in days_of(export_kind):
        raise BundleError("transfer_day_not_in_export_kind")
    if receipt.get("status") != "SEALED" or receipt.get("format") != "v0.2":
        raise BundleError("transfer_receipt_not_sealed")
    if receipt.get("kind") != RECEIPT_KIND[export_kind]:
        raise BundleError("transfer_receipt_kind_mismatch")
    if receipt.get("day") != day.isoformat():
        raise BundleError("transfer_receipt_day_mismatch")
    if manifest.get("format") != FORMAT_V02:
        raise BundleError("transfer_bundle_not_v02")
    bundle = receipt.get("bundle")
    files = bundle.get("files") if isinstance(bundle, dict) else None
    streams = manifest.get("streams")
    if not isinstance(files, dict) or not isinstance(streams, list):
        raise BundleError("transfer_receipt_bundle_mismatch")
    out = {}
    for stream in streams:
        if not isinstance(stream, dict) or set(stream) != {"path", "sha256", "bytes", "records"}:
            raise BundleError("transfer_receipt_bundle_mismatch")
        name = stream["path"]
        if (not isinstance(name, str) or name in out
                or files.get(name) != dict(bytes=stream["bytes"], sha256=stream["sha256"])):
            raise BundleError("transfer_receipt_bundle_mismatch")
        out[name] = dict(sha256=stream["sha256"], bytes=stream["bytes"], records=stream["records"])
    if files.get("bundle.json", {}).get("sha256") != manifest_hash or set(files) != {"bundle.json", *out}:
        raise BundleError("transfer_receipt_bundle_mismatch")
    v01 = bundle.get("v01_equivalent")
    module = receipt.get("module_sha256")
    if not isinstance(v01, dict) or not _hex(v01.get("sha256")) or not _hex(module):
        raise BundleError("transfer_receipt_bundle_mismatch")
    return dict(day=day.isoformat(), export_kind=export_kind, format="v0.2", bundle_json_sha256=manifest_hash,
                receipt_sha256=receipt_hash, module_sha256=module, v01_equivalent_sha256=v01["sha256"],
                streams=dict(sorted(out.items())))


def _hex(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _key(entry):
    return entry["day"], EXPORT_KINDS.index(entry["export_kind"])


def build(roots, *, host_id, created_at):
    """``roots``: ``[(export_kind, day folder)]``. Capture host; reads only bundle.json and receipt.json."""
    if not 1 <= len(roots) <= MAX_BUNDLES or not isinstance(host_id, str) or not host_id:
        raise BundleError("transfer_root_invalid")
    entries = [_entry(kind, root) for kind, root in roots]
    keys = [(e["day"], e["export_kind"]) for e in entries]
    if len(set(keys)) != len(keys):
        raise BundleError("transfer_duplicate_bundle")
    return dict(format=FORMAT, bundles=sorted(entries, key=_key), host_id=host_id, created_at=created_at)


def check_doc(doc):
    """The committed document's shape: format, unique sorted keys, every field present and typed."""
    if not isinstance(doc, dict) or set(doc) != DOC_FIELDS or doc["format"] != FORMAT:
        raise BundleError("transfer_manifest_invalid")
    bundles = doc["bundles"]
    if not isinstance(bundles, list) or not 1 <= len(bundles) <= MAX_BUNDLES:
        raise BundleError("transfer_manifest_invalid")
    for entry in bundles:
        if (not isinstance(entry, dict) or set(entry) != ENTRY_FIELDS or entry["export_kind"] not in EXPORT_KINDS
                or entry["format"] != "v0.2" or not isinstance(entry["day"], str)
                or not all(_hex(entry[k]) for k in ("bundle_json_sha256", "receipt_sha256", "module_sha256",
                                                    "v01_equivalent_sha256"))
                or not isinstance(entry["streams"], dict) or not entry["streams"]
                or any(not isinstance(v, dict) or set(v) != STREAM_FIELDS for v in entry["streams"].values())):
            raise BundleError("transfer_manifest_invalid")
        if _day(entry["day"]) not in days_of(entry["export_kind"]):
            raise BundleError("transfer_manifest_invalid")
    keys = [_key(e) for e in bundles]
    if keys != sorted(set(keys)):
        raise BundleError("transfer_manifest_invalid")
    return {(e["day"], e["export_kind"]): e for e in bundles}


def _mismatch(day, field):
    return BundleError(f"transfer_manifest_mismatch:{day}:{field}")


def verify(doc, roots, *, limits=None, clock=time.monotonic):
    """``roots``: ``[(export_kind, day folder)]``. Workstation; returns ``[(export_kind, StreamBundle)]``.

    Every comparison happens before a record is parsed: raw manifest and receipt hashes first, then
    pass one of the stream reader.
    """
    listed = check_doc(doc)
    opened, seen = [], set()
    for export_kind, root in roots:
        if export_kind not in EXPORT_KINDS:
            raise BundleError("transfer_export_kind_unknown")
        root = regular_path(root)
        manifest, manifest_hash = _read(root / "bundle" / "bundle.json", MAX_MANIFEST_BYTES)
        day = _day(manifest.get("day"))
        key = (day.isoformat(), export_kind)
        if key not in listed:
            raise BundleError(f"transfer_manifest_unlisted:{key[0]}:{export_kind}")
        if key in seen:
            raise BundleError("transfer_duplicate_bundle")
        seen.add(key)
        entry = listed[key]
        if manifest_hash != entry["bundle_json_sha256"]:
            raise _mismatch(key[0], "bundle_json_sha256")
        _, receipt_hash = _read(root / "receipt.json", MAX_RECEIPT_BYTES)
        if receipt_hash != entry["receipt_sha256"]:
            raise _mismatch(key[0], "receipt_sha256")
        current = _entry(export_kind, root)
        for field in sorted(ENTRY_FIELDS - {"streams"}):
            if current[field] != entry[field]:
                raise _mismatch(key[0], field)
        bundle = open_stream_bundle(root / "bundle", limits=limits, clock=clock)
        if bundle.format != FORMAT_V02 or bundle.day != day:
            raise _mismatch(key[0], "format")
        refs = {ref.name: dict(sha256=ref.sha256, bytes=ref.bytes, records=ref.records) for ref in bundle.streams}
        for name in sorted(set(refs) | set(entry["streams"])):
            if refs.get(name) != entry["streams"].get(name):
                raise _mismatch(key[0], f"streams.{name}")
        if bundle.input_hashes.get("bundle.json") != entry["bundle_json_sha256"]:
            raise _mismatch(key[0], "bundle_json_sha256")
        opened.append((export_kind, bundle))
    return opened
