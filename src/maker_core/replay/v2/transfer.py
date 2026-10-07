"""The bundle transfer manifest: capture-host build, workstation verify (maker replay v2 W7; reg §8).

Owner decision 19 (A-defender M9): the committed manifest lives at ``TRANSFER_MANIFEST_PATH`` and is
keyed **per bundle**, by ``(day, export_kind)``, because a calibration date carries several bundles.
``export_kind`` is one of:

=============================  ==========================  ===============  ===========================
export_kind                    day set (``panel``)         ``receipt.kind``  bundle formats
=============================  ==========================  ===============  ===========================
``panel_night``                ``QUOTE_DATES``             ``panel``        v0.2, v0.3
``settlement_night``           ``SETTLEMENT_ONLY_DATES``   ``panel``        v0.2, v0.3
``calibration_night``          ``CALIBRATION_DATES``       ``panel``        v0.2, v0.3
``calibration_hazard``         ``CALIBRATION_DATES``       ``calibration``  v0.2, v0.3
``calibration_v01_reference``  ``CALIBRATION_DATES``       ``calibration``  v0.1 (the E3 reference, PM4)
=============================  ==========================  ===============  ===========================

A root is one exported day folder as the night exporters write it: ``<root>/receipt.json`` and
``<root>/bundle/``. The bundle folder holds exactly ``bundle.json``, ``export.json`` and the manifest's
streams; the receipt's ``bundle.files`` must digest exactly those files. ``export.json`` is bound by hash.

Formats (``FORMATS``): v0.1 and v0.2 streams are plain JSON lines (stream fields ``path sha256 bytes
records``), and a stream's identity is its ``sha256``/``bytes``/``records``. v0.3 (X1, deterministic gzip,
``<kind>.jsonl.gz``) streams also carry ``decoded_sha256`` and ``decoded_bytes``: the stream identity is
then ``decoded_sha256``/``decoded_bytes``/``records`` (equal to the receipt's per-kind decoded digests,
re-derived by pass one under the decompressor), while the stored ``sha256``/``bytes`` are recorded in the
entry as ``stored_sha256``/``stored_bytes`` only, because stored gzip bytes are not portable across zlib
builds (owner decision 8). ``bundle.json`` itself, which lists the stored hashes, is still bound by hash. The decoder is X1's ``maker_core.replay.v2.gzip_stream``,
imported only when a v0.3 stream is checked, so this module works on trees with or without X1.

Every bundle must declare ``provenance == "captured"`` (U1 Defender MF3; ``transfer_bundle_not_captured``):
a relabelled synthetic bundle could otherwise run without declared intervals.

- ``build(roots, *, host_id, created_at)`` runs on the capture host and reads only ``bundle.json``,
  ``export.json`` and ``receipt.json``. It applies integrity rule PB2(a): every input key of
  ``export.json``'s ``input_hashes``, and of the receipt's ``input_hashes`` when present, is
  ``carry:YYYY-MM-DD`` (a real calendar date) or an optional ``release:`` prefix plus a normalised
  relative ``/`` path (see ``_normalised``: ASCII printable, at most ``MAX_INPUT_KEY_CHARS``, no
  backslash, ``:``, ``~`` (8.3 short names) or other Windows-invalid character, no leading ``/``, no
  empty, ``.`` or ``..`` segment, no segment ending in a dot or space, no device name; U1 Defender r2
  NOTE-2, U1r2 Defender NOTE-2 and D-1), and every path whose
  first segment is case-insensitively ``maker_evidence`` lies under ``maker_evidence/<day>/`` exactly
  (cumulative non-evidence inputs are PB2(c): allowed and disclosed).
- ``verify(doc, roots, *, bounds_check=True, limits=None, clock=..., run=None)`` runs on the workstation.
  Each of ``bundle.json``, ``export.json`` and ``receipt.json`` is read by this module once; its raw
  bytes are hashed and compared with the listed entry BEFORE this module parses them, and this module
  parses only those same bytes (U1 Defender N1 and r2 LOW-1). Nothing that does not match a listed entry
  of the caller's ``export_kind`` is parsed here, except ``bundle.json`` to name an unlisted refusal. Then
  every ``build`` check is re-applied to those bytes and the reader's pass one runs (every stream hashed,
  sized, counted and, for v0.3, decoded). **Known gap (U1r2 Defender LOW-A, open X1 follow-up before
  sha2):** ``open_stream_bundle`` re-reads ``bundle.json`` from disk and parses it to drive pass one;
  that second copy's hash is compared with the entry only afterwards (``bundle.input_hashes``). A swap
  between the two reads fails closed, but its bytes are parsed first. The fix is X1's: an
  ``open_stream_bundle`` that takes the expected manifest hash (or the verified bytes). With ``bounds`` (PB2(b), the default) it then scans each stream once and
  refuses ``transfer_bounds_outside_day:<day>:<stream>`` unless every record's ``captured_at`` lies in
  ``[day 00:00Z, day+1 00:00Z)``. The scan reports only counts and the min/max ``captured_at`` per
  stream; no row leaves it.
- Limits (U1 Defender r2 C2): bundles open under X1's ``V2Limits`` (``limits``, default ``V2Limits()``),
  and every open, pass and bounds scan of one ``verify`` call shares ONE ``RunBudget`` (``run``, default
  one built on ``clock``). Up to ``MAX_BUNDLES`` bundles are bounded by the run's deadline and stored
  total, not by one 32,768 s lifetime per bundle.

Refusals name ``transfer_manifest_mismatch:<day>:<field>``, ``transfer_manifest_unlisted:<day>:<kind>``,
``transfer_inputs_outside_day:<day>`` and the codes in ``REFUSAL_CODES``.

O9 (bundle transfer to the workstation) is on HOLD: this module is code and fictional tests only.
"""
from __future__ import annotations

from datetime import date, datetime, time as clock_time, timedelta, timezone
import hashlib
import json
import re
import time
from typing import NamedTuple

from maker_core.replay.bundle import (MAX_LINE_BYTES, MAX_MANIFEST_BYTES, BundleError, Limits, _Reader,
                                      regular_path, sha256, timestamp)
from maker_core.replay.bundle_v02 import open_stream_bundle
from maker_core.replay.v2 import panel as constants
from maker_core.replay.v2.limits import RunBudget, coerce

FORMAT = "maker_core.replay.v2.transfer.v0.2"
TRANSFER_MANIFEST_PATH = "config/maker_replay_v2/transfer_manifest.json"
MAX_RECEIPT_BYTES = 4 * 1024**2
MAX_EXPORT_BYTES = 16 * 1024**2
MAX_BUNDLES = 32
CHUNK_BYTES = 1024**2
PLAIN_FIELDS = frozenset({"path", "sha256", "bytes", "records"})
GZIP_FIELDS = PLAIN_FIELDS | {"decoded_sha256", "decoded_bytes"}
# bundle.json format -> (receipt format label, stream fields, stream name pattern, encoding)
FORMATS = {
    "maker_core.replay.bundle.v0.1": ("v0.1", PLAIN_FIELDS, r"[a-zA-Z0-9_-]+\.jsonl", "identity"),
    "maker_core.replay.bundle.v0.2": ("v0.2", PLAIN_FIELDS, r"[a-zA-Z0-9_-]+\.jsonl", "identity"),
    "maker_core.replay.bundle.v0.3": ("v0.3", GZIP_FIELDS, r"[a-zA-Z0-9_-]+\.jsonl\.gz", "gzip"),
}
V2_FORMATS = ("maker_core.replay.bundle.v0.2", "maker_core.replay.bundle.v0.3")
EXPORT_KINDS = ("panel_night", "settlement_night", "calibration_night", "calibration_hazard",
                "calibration_v01_reference")
RECEIPT_KIND = dict(panel_night="panel", settlement_night="panel", calibration_night="panel",
                    calibration_hazard="calibration", calibration_v01_reference="calibration")
KIND_FORMATS = dict(panel_night=V2_FORMATS, settlement_night=V2_FORMATS, calibration_night=V2_FORMATS,
                    calibration_hazard=V2_FORMATS, calibration_v01_reference=("maker_core.replay.bundle.v0.1",))
ENTRY_FIELDS = frozenset({"day", "export_kind", "format", "bundle_format", "bundle_json_sha256",
                          "export_json_sha256", "receipt_sha256", "module_sha256", "v01_equivalent_sha256",
                          "streams"})
DOC_FIELDS = frozenset({"format", "bundles", "host_id", "created_at"})
EVIDENCE_PREFIX = "maker_evidence/"
MAX_INPUT_KEY_CHARS = 512
_CARRY_KEY = re.compile(r"carry:\d{4}-\d{2}-\d{2}")
_RELEASE_PREFIX = "release:"
_WINDOWS_INVALID = set('<>:"|?*~')  # ``~``: 8.3 short names (``MAKER_~1``) alias long ones
_DEVICE_NAMES = frozenset({"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
                           *(f"{d}{i}" for d in ("COM", "LPT") for i in range(10))})
REFUSAL_CODES = ("transfer_root_invalid", "transfer_export_kind_unknown", "transfer_day_not_in_export_kind",
                 "transfer_receipt_not_sealed", "transfer_receipt_kind_mismatch", "transfer_receipt_day_mismatch",
                 "transfer_bundle_day_mismatch", "transfer_bundle_format_not_allowed",
                 "transfer_receipt_bundle_mismatch", "transfer_export_mismatch", "transfer_inputs_outside_day",
                 "transfer_duplicate_bundle", "transfer_manifest_invalid", "transfer_manifest_unlisted",
                 "transfer_manifest_mismatch", "transfer_bounds_outside_day", "transfer_decoder_unavailable",
                 "transfer_bundle_not_captured")


class Verified(NamedTuple):
    export_kind: str
    bundle: object  # the StreamBundle after pass one
    bounds: dict | None  # stream -> {records, min_captured_at, max_captured_at} (PB2(b)); None without bounds


def days_of(export_kind):
    if export_kind == "panel_night":
        return tuple(constants.QUOTE_DATES)
    if export_kind == "settlement_night":
        return tuple(constants.SETTLEMENT_ONLY_DATES)
    if export_kind in ("calibration_night", "calibration_hazard", "calibration_v01_reference"):
        return tuple(constants.CALIBRATION_DATES)
    raise BundleError("transfer_export_kind_unknown")


def _raw(path, cap):
    raw = _Reader(Limits(cap, 1, 30), time.monotonic).read(regular_path(path), cap)
    return raw, sha256(raw)


def _parse(raw):
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:  # nesting depth: still a BundleError
        raise BundleError("transfer_root_invalid") from exc
    if not isinstance(value, dict):
        raise BundleError("transfer_root_invalid")
    return value


def _read(path, cap, given=None):
    """``(parsed, sha256)`` of exactly one read; ``given`` is ``(raw, sha256)`` already read and compared."""
    raw, digest = _raw(path, cap) if given is None else given
    return _parse(raw), digest


def _day(value):
    try:
        day = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise BundleError("transfer_root_invalid") from exc
    if day.isoformat() != value:
        raise BundleError("transfer_root_invalid")
    return day


def _hex(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _bundle_folder(root):
    folder = regular_path(root / "bundle")
    names = sorted(p.name for p in folder.iterdir()) if folder.is_dir() else None
    if names is None:
        raise BundleError("transfer_root_invalid")
    return folder, names


def _inputs_rule(day, export, receipt):
    """PB2(a): every capture input key lies under that day's ``maker_evidence/<day>/`` folder."""
    inputs = export.get("input_hashes")
    if not isinstance(inputs, dict) or not inputs:
        raise BundleError("transfer_export_mismatch")
    later = receipt.get("input_hashes", {})  # the receipt's (possibly trimmed) post-export view
    if not isinstance(later, dict):
        raise BundleError("transfer_export_mismatch")
    own = f"{EVIDENCE_PREFIX}{day}/"
    for key in (*inputs, *later):
        path = _normalised(key)
        if path is None or (path.split("/")[0].casefold() == EVIDENCE_PREFIX[:-1]
                            and not path.startswith(own)):
            raise BundleError(f"transfer_inputs_outside_day:{day}")


def _normalised(key):
    """The path part of an input key as the exporter's reader writes it, or ``None`` (U1r2 Defender NOTE-2).

    Keys are ``carry:YYYY-MM-DD`` (no path), ``release:<path>`` or ``<path>``. A key is ASCII printable and
    at most ``MAX_INPUT_KEY_CHARS`` long; a path is relative ``/`` (``Path.relative_to(root)``): no
    backslash, ``:`` (drive letters, ADS), ``~`` (8.3 short names such as ``MAKER_~1``, U1r2 Defender D-1)
    or other Windows-invalid character, no leading ``/``, no empty,
    ``.`` or ``..`` segment, no segment ending in a dot or space (Win32 strips those, so
    ``maker_evidence./<other day>`` would alias another day's folder) and no device name segment.
    """
    if (not isinstance(key, str) or len(key) > MAX_INPUT_KEY_CHARS or not key.isascii()
            or not key.isprintable()):
        return None
    if _CARRY_KEY.fullmatch(key):
        try:
            date.fromisoformat(key.removeprefix("carry:"))
        except ValueError:
            return None
        return ""
    path = key.removeprefix(_RELEASE_PREFIX)
    if not path or _WINDOWS_INVALID & set(path) or "\\" in path or path.startswith("/"):
        return None
    for part in path.split("/"):
        if part in ("", ".", "..") or part[-1] in ". " or (
                part.split(".")[0].rstrip(" ").upper() in _DEVICE_NAMES):
            return None
    return path


def _entry(export_kind, root, raws=None):
    """One root's entry from ``bundle.json``, ``export.json`` and ``receipt.json`` only.

    ``raws`` (from ``verify``): ``{"receipt", "bundle", "export"} -> (raw, sha256)`` already read and
    compared; those exact bytes are parsed and nothing is re-read from disk.
    """
    raws = raws or {}
    if export_kind not in EXPORT_KINDS:
        raise BundleError("transfer_export_kind_unknown")
    root = regular_path(root)
    folder, names = _bundle_folder(root)
    receipt, receipt_hash = _read(root / "receipt.json", MAX_RECEIPT_BYTES, raws.get("receipt"))
    manifest, manifest_hash = _read(folder / "bundle.json", MAX_MANIFEST_BYTES, raws.get("bundle"))
    export, export_hash = _read(folder / "export.json", MAX_EXPORT_BYTES, raws.get("export"))
    day = _day(manifest.get("day"))
    if day not in days_of(export_kind):
        raise BundleError("transfer_day_not_in_export_kind")
    bundle_format = manifest.get("format")
    if bundle_format not in KIND_FORMATS[export_kind]:
        raise BundleError("transfer_bundle_format_not_allowed")
    label, fields, pattern, encoding = FORMATS[bundle_format]
    if manifest.get("provenance") != "captured":
        raise BundleError("transfer_bundle_not_captured")
    if receipt.get("status") != "SEALED" or receipt.get("format", "v0.1") != label:
        raise BundleError("transfer_receipt_not_sealed")
    if receipt.get("kind") != RECEIPT_KIND[export_kind]:
        raise BundleError("transfer_receipt_kind_mismatch")
    if receipt.get("day") != day.isoformat() or export.get("day") != day.isoformat():
        raise BundleError("transfer_receipt_day_mismatch")
    bundle = receipt.get("bundle")
    files = bundle.get("files") if isinstance(bundle, dict) else None
    streams = manifest.get("streams")
    if not isinstance(files, dict) or not isinstance(streams, list) or not streams:
        raise BundleError("transfer_receipt_bundle_mismatch")
    out = {}
    for stream in streams:
        if not isinstance(stream, dict) or set(stream) != fields:
            raise BundleError("transfer_receipt_bundle_mismatch")
        name = stream["path"]
        if (not isinstance(name, str) or re.fullmatch(pattern, name) is None or name in out
                or name in ("bundle.json", "export.json")
                or files.get(name) != dict(bytes=stream["bytes"], sha256=stream["sha256"])):
            raise BundleError("transfer_receipt_bundle_mismatch")
        out[name] = _identity(stream, encoding)
        if encoding == "gzip":
            kinds = bundle.get("kinds") if isinstance(bundle.get("kinds"), dict) else {}
            declared = kinds.get(name[:-len(".jsonl.gz")], {})
            if (declared.get("decoded_sha256"), declared.get("decoded_bytes")) != (
                    stream["decoded_sha256"], stream["decoded_bytes"]):
                raise BundleError("transfer_receipt_bundle_mismatch")
    expected_files = {"bundle.json", "export.json", *out}
    if (set(files) != expected_files or set(names) != expected_files
            or files["bundle.json"].get("sha256") != manifest_hash
            or files["export.json"].get("sha256") != export_hash):
        raise BundleError("transfer_receipt_bundle_mismatch")
    module = receipt.get("module_sha256")
    if bundle_format in V2_FORMATS:
        v01 = bundle.get("v01_equivalent")
        v01_sha = v01.get("sha256") if isinstance(v01, dict) else None
    else:  # the v0.1 reference's events stream is itself the v0.1 bytes E3 compares
        v01_sha = out["events.jsonl"]["sha256"] if "events.jsonl" in out else None
    if not isinstance(v01_sha, str):
        v01_sha = None
    if not _hex(v01_sha) or not _hex(module):
        raise BundleError("transfer_receipt_bundle_mismatch")
    _inputs_rule(day.isoformat(), export, receipt)
    return dict(day=day.isoformat(), export_kind=export_kind, format=label, bundle_format=bundle_format,
                bundle_json_sha256=manifest_hash, export_json_sha256=export_hash, receipt_sha256=receipt_hash,
                module_sha256=module, v01_equivalent_sha256=v01_sha, streams=dict(sorted(out.items())))


def _identity(stream, encoding):
    """A stream's entry: plain streams by stored bytes; gzip streams by decoded bytes, stored ones recorded."""
    if encoding == "gzip":
        return dict(decoded_sha256=stream["decoded_sha256"], decoded_bytes=stream["decoded_bytes"],
                    records=stream["records"], stored_sha256=stream["sha256"], stored_bytes=stream["bytes"])
    return dict(sha256=stream["sha256"], bytes=stream["bytes"], records=stream["records"])


STREAM_ENTRY = {"identity": frozenset({"sha256", "bytes", "records"}),
                "gzip": frozenset({"decoded_sha256", "decoded_bytes", "records", "stored_sha256", "stored_bytes"})}
IDENTITY = {"identity": ("sha256", "bytes", "records"), "gzip": ("decoded_sha256", "decoded_bytes", "records")}


def _key(entry):
    return entry["day"], EXPORT_KINDS.index(entry["export_kind"])


def build(roots, *, host_id, created_at):
    """``roots``: ``[(export_kind, day folder)]``. Capture host; reads no stream byte."""
    if not 1 <= len(roots) <= MAX_BUNDLES or not isinstance(host_id, str) or not host_id:
        raise BundleError("transfer_root_invalid")
    entries = [_entry(kind, root) for kind, root in roots]
    keys = [(e["day"], e["export_kind"]) for e in entries]
    if len(set(keys)) != len(keys):
        raise BundleError("transfer_duplicate_bundle")
    return dict(format=FORMAT, bundles=sorted(entries, key=_key), host_id=host_id, created_at=created_at)


def check_doc(doc):
    """The committed document's shape: format, unique sorted keys, every field present and typed."""
    if (not isinstance(doc, dict) or set(doc) != DOC_FIELDS or doc["format"] != FORMAT
            or not isinstance(doc["host_id"], str) or not doc["host_id"] or not isinstance(doc["created_at"], str)):
        raise BundleError("transfer_manifest_invalid")
    bundles = doc["bundles"]
    if not isinstance(bundles, list) or not 1 <= len(bundles) <= MAX_BUNDLES:
        raise BundleError("transfer_manifest_invalid")
    for entry in bundles:
        if (not isinstance(entry, dict) or set(entry) != ENTRY_FIELDS or entry["export_kind"] not in EXPORT_KINDS
                or entry["bundle_format"] not in KIND_FORMATS[entry["export_kind"]]
                or entry["format"] != FORMATS[entry["bundle_format"]][0] or not isinstance(entry["day"], str)
                or not all(_hex(entry[k]) for k in ("bundle_json_sha256", "export_json_sha256", "receipt_sha256",
                                                    "module_sha256", "v01_equivalent_sha256"))
                or not isinstance(entry["streams"], dict) or not entry["streams"]
                or any(not isinstance(v, dict) or set(v) != STREAM_ENTRY[FORMATS[entry["bundle_format"]][3]]
                       for v in entry["streams"].values())):
            raise BundleError("transfer_manifest_invalid")
        if _day(entry["day"]) not in days_of(entry["export_kind"]):
            raise BundleError("transfer_manifest_invalid")
    keys = [_key(e) for e in bundles]
    if keys != sorted(set(keys)):
        raise BundleError("transfer_manifest_invalid")
    return {(e["day"], e["export_kind"]): e for e in bundles}


def _mismatch(day, field):
    return BundleError(f"transfer_manifest_mismatch:{day}:{field}")


def _opened_stream(ref):
    """What pass one measured for one stream: its identity fields only (decoded ones for gzip)."""
    if getattr(ref, "encoding", "identity") == "gzip":
        return dict(decoded_sha256=ref.decoded_sha256, decoded_bytes=ref.decoded_bytes, records=ref.records)
    return dict(sha256=ref.sha256, bytes=ref.bytes, records=ref.records)


def _decoder():
    try:
        from maker_core.replay.v2 import gzip_stream
    except ImportError as exc:  # a tree without X1 cannot have admitted a v0.3 bundle in pass one
        raise BundleError("transfer_decoder_unavailable") from exc
    return gzip_stream


def _lines(path, ref, encoding, check):
    """The stream's decoded lines, re-hashing the stored bytes (and decoded bytes) as they pass."""
    stored, decoded = hashlib.sha256(), hashlib.sha256()
    with path.open("rb") as handle:
        def chunks():
            while chunk := handle.read(CHUNK_BYTES):
                check()
                stored.update(chunk)
                yield chunk
        if encoding == "gzip":
            gzip_stream = _decoder()
            limit = ref.decoded_bytes
            lines = gzip_stream.lines(gzip_stream.decode(chunks(), limit, check=check), MAX_LINE_BYTES)
        else:
            lines = _split(chunks())
        for line in lines:
            decoded.update(line)
            yield line
    if stored.hexdigest() != ref.sha256 or (encoding == "gzip" and decoded.hexdigest() != ref.decoded_sha256):
        raise BundleError("input_changed_between_passes")


def _split(chunks):
    pending = b""
    for chunk in chunks:
        pending += chunk
        *complete, pending = pending.split(b"\n")
        for line in complete:
            if len(line) + 1 > MAX_LINE_BYTES:
                raise BundleError("record_too_large_or_unterminated")
            yield line + b"\n"
        if len(pending) > MAX_LINE_BYTES:
            raise BundleError("record_too_large_or_unterminated")
    if pending:
        raise BundleError("record_too_large_or_unterminated")


def bounds(bundle, *, check=lambda: None):
    """PB2(b): per stream, the record count and min/max ``captured_at``; refuses any outside the day.

    Order-free, so it also covers the v0.1 reference's sequence-ordered ``events.jsonl``. Only these
    three values per stream leave the scan. The scan is one pass of the bundle: its own pass clock and the
    bundle's run budget (the run ``verify`` opened it with) bind every chunk and record.
    """
    reader, caller = bundle.pass_reader(), check

    def check():
        reader.check()
        caller()
    start = datetime.combine(bundle.day, clock_time(), tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    result = {}
    for ref in bundle.streams:
        encoding = getattr(ref, "encoding", "identity")
        count, low, high = 0, None, None
        for line in _lines(regular_path(bundle.root / ref.name), ref, encoding, check):
            check()
            try:
                value = json.loads(line)
                at = timestamp(value["captured_at"])
            except (ValueError, TypeError, KeyError, RecursionError) as exc:  # nesting depth (LOW-B)
                raise BundleError(f"transfer_bounds_outside_day:{bundle.day}:{ref.name}") from exc
            if not start <= at < end:
                raise BundleError(f"transfer_bounds_outside_day:{bundle.day}:{ref.name}")
            count += 1
            low = at if low is None or at < low else low
            high = at if high is None or at > high else high
        if count != ref.records:
            raise BundleError("input_changed_between_passes")
        result[ref.name] = dict(records=count, min_captured_at=low.isoformat() if low else None,
                                max_captured_at=high.isoformat() if high else None)
    return result


def verify(doc, roots, *, bounds_check=True, limits=None, clock=time.monotonic, run=None):
    """``roots``: ``[(export_kind, day folder)]``. Workstation; returns ``[Verified]``.

    Every comparison happens before a record is parsed: raw manifest, export and receipt hashes (each
    file read here once, hashed and compared, and only then parsed here), then every ``build`` check on
    those same bytes, then pass one of the stream reader. The reader re-reads and parses ``bundle.json``
    before its own copy's hash is compared (LOW-A, see the module docstring; X1 follow-up). The PB2(b) bounds scan runs last. ``run`` is the ONE
    ``RunBudget`` of this verify (built on ``clock`` when omitted), shared by every bundle.
    """
    listed = check_doc(doc)
    limits = coerce(limits)
    if run is None:
        run = RunBudget(clock=clock)
    elif not isinstance(run, RunBudget):
        raise BundleError("invalid_limits")
    opened, seen = [], set()
    for export_kind, root in roots:
        run.check()
        if export_kind not in EXPORT_KINDS:
            raise BundleError("transfer_export_kind_unknown")
        root = regular_path(root)
        raw, manifest_hash = _raw(root / "bundle" / "bundle.json", MAX_MANIFEST_BYTES)
        matches = [k for k, e in listed.items() if e["export_kind"] == export_kind
                   and e["bundle_json_sha256"] == manifest_hash]
        if not matches:  # nothing verified: parse only to name the refusal
            day = _day(_parse(raw).get("day")).isoformat()
            if (day, export_kind) not in listed:
                raise BundleError(f"transfer_manifest_unlisted:{day}:{export_kind}")
            raise _mismatch(day, "bundle_json_sha256")
        key = matches[0]
        if key in seen:
            raise BundleError("transfer_duplicate_bundle")
        seen.add(key)
        entry = listed[key]
        day = _day(_parse(raw).get("day"))
        if day.isoformat() != key[0]:
            raise _mismatch(key[0], "day")
        export_raw = _raw(root / "bundle" / "export.json", MAX_EXPORT_BYTES)
        if export_raw[1] != entry["export_json_sha256"]:  # compared before any parse (LOW-1)
            raise _mismatch(key[0], "export_json_sha256")
        receipt_raw = _raw(root / "receipt.json", MAX_RECEIPT_BYTES)
        if receipt_raw[1] != entry["receipt_sha256"]:
            raise _mismatch(key[0], "receipt_sha256")
        current = _entry(export_kind, root, dict(receipt=receipt_raw, bundle=(raw, manifest_hash),
                                                 export=export_raw))
        for field in sorted(ENTRY_FIELDS):
            if current[field] != entry[field]:
                raise _mismatch(key[0], field)
        bundle = open_stream_bundle(root / "bundle", limits=limits, clock=clock, run=run)
        if bundle.format != entry["bundle_format"] or bundle.day != day:
            raise _mismatch(key[0], "bundle_format")
        if bundle.provenance != "captured":
            raise BundleError("transfer_bundle_not_captured")
        identity = IDENTITY[FORMATS[entry["bundle_format"]][3]]
        refs = {ref.name: _opened_stream(ref) for ref in bundle.streams}
        for name in sorted(set(refs) | set(entry["streams"])):
            listed_stream = entry["streams"].get(name)
            if listed_stream is None or refs.get(name) != {k: listed_stream[k] for k in identity}:
                raise _mismatch(key[0], f"streams.{name}")
        if bundle.input_hashes.get("bundle.json") != entry["bundle_json_sha256"]:
            raise _mismatch(key[0], "bundle_json_sha256")
        opened.append([export_kind, bundle])
    for item in opened:
        item.append(bounds(item[1]) if bounds_check else None)
    return [Verified(*item) for item in opened]
