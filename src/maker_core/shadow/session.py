"""Frozen admission and create-only, sealed segments using the existing journal."""
from dataclasses import dataclass, fields
from datetime import date, timedelta
import hashlib
import os
from pathlib import Path
import re
import shutil

from maker_core.contracts import CONTRACTS_VERSION, utc_time
from maker_core.evidence.journal import Journal, SecretGuard, canonical_bytes, digest, verify_journal
from maker_core.replay.bundle import regular_path, _json
from maker_core.replay.lifecycle import ReplayConfig
from maker_core.shadow.codec import checked, decode

SESSION_SCHEMA = "maker_shadow_session_v0.1"
SEAL_SCHEMA = "maker_shadow_seal_v0.1"
RECEIPT_SCHEMA = "maker_shadow_receipt_v0.1"


@dataclass(frozen=True)
class Manifest:
    run_id: str
    code_revision: str
    plugin_identity: str
    model_identity: str
    configuration_digest: str
    registration_digest: str
    conditions: tuple
    target_dates: tuple
    start: object
    end: object
    config: ReplayConfig
    hazard_label: str
    mode: str = "diagnostic"
    parent_run: str | None = None
    max_events: int = 200_000
    max_bytes: int = 256 * 1024**2
    segment_bytes: int = 16 * 1024**2
    min_free_bytes: int = 1024**3

    def __post_init__(self):
        utc_time(self.start)
        utc_time(self.end)
        object.__setattr__(self, "conditions", tuple(self.conditions))
        object.__setattr__(self, "target_dates", tuple(tuple(v) for v in self.target_dates))
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", self.run_id):
            raise ValueError("invalid_run_id")
        if not re.fullmatch(r"[0-9a-f]{40}", self.code_revision):
            raise ValueError("code_revision_required")
        for value in (self.configuration_digest, self.registration_digest):
            if not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ValueError("frozen_digest_required")
        if (not self.plugin_identity or not self.model_identity or not self.hazard_label
                or not timedelta(0) < self.end - self.start <= timedelta(days=14)):
            raise ValueError("missing_or_unbounded_admission")
        if (self.mode not in ("diagnostic", "drill", "shadow") or self.config.policy != "informed-v0"
                or self.config.max_book_gap_seconds != 10 or self.config.hazard_per_minute is None
                or self.config.fill_bound != "strictly_through"):
            raise ValueError("shadow_configuration_refused")
        if self.hazard_label == "synthetic" and self.mode != "drill":
            raise ValueError("synthetic_hazard_requires_drill")
        ids = {c.condition_id for c in self.conditions}
        if (not 1 <= len(ids) == len(self.conditions) == len(self.target_dates) <= 32
                or ids != {c for c, _ in self.target_dates}):
            raise ValueError("invalid_frozen_scope")
        for _, day in self.target_dates:
            date.fromisoformat(day)
        for c in self.conditions:
            utc_time(c.active_from)
            utc_time(c.active_until)
            if not self.start <= c.active_from < c.active_until <= self.end:
                raise ValueError("condition_outside_session")
        if self.parent_run is not None and self.mode == "shadow":
            raise ValueError("unverified_restart_continuity")
        for v, lo, hi in ((self.max_events, 1, 500_000), (self.max_bytes, 262144, 1024**3),
                          (self.segment_bytes, 65536, 64*1024**2),
                          (self.min_free_bytes, 1024**2, 100*1024**3)):
            if type(v) is not int or not lo <= v <= hi:
                raise ValueError("invalid_resource_ceiling")

    def projection(self):
        return {"schema_version": SESSION_SCHEMA, "contract_revision": CONTRACTS_VERSION,
                "public_allowlist": ["clob-book", "clob-rewards", "gamma-events", "market-stream"],
                **{f.name: checked(getattr(self, f.name)) for f in fields(self)}}

    @classmethod
    def restore(cls, payload):
        names = {f.name for f in fields(cls)}
        if set(payload) != names | {"schema_version", "contract_revision", "public_allowlist"}:
            raise ValueError("manifest_fields")
        result = cls(**{k: decode(payload[k]) for k in names})
        if canonical_bytes(payload) != canonical_bytes(result.projection()):
            raise ValueError("manifest_contract_changed")
        return result


def write_bytes(path, raw):
    path = regular_path(path)
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


class Tape:
    """Directory creation is the process-independent writer claim; never reused."""
    def __init__(self, root, manifest):
        self.root, self.manifest = regular_path(root), manifest
        self.root.mkdir(parents=True, exist_ok=False)
        (self.root / "inputs").mkdir()
        self.now, self.size, self.segment, self.rows = manifest.start, 0, 0, 0
        self.seals, self.artifacts = [], {}
        self.failed, self.closed = False, False
        self.manifest_hash = digest(manifest.projection())
        self._write(self.root / "manifest.json", canonical_bytes(manifest.projection()))
        self._open(None)

    def _write(self, path, raw):
        try:
            self._budget(len(raw))
            write_bytes(path, raw)
            self.size += len(raw)
        except BaseException:
            self.failed = True
            raise

    def _budget(self, extra):
        if (self.size + extra + 32768 > self.manifest.max_bytes
                or shutil.disk_usage(self.root).free < self.manifest.min_free_bytes + extra):
            raise ValueError("shadow_storage_ceiling")

    def _open(self, previous):
        self.path = self.root / f"quotes-{self.segment:05d}.jsonl"
        self.day = self.now.date()
        self.journal = Journal(self.path, clock=lambda: self.now, mode="hypothetical",
                               scope={"run_id": self.manifest.run_id, "segment": self.segment,
                                      "manifest_digest": self.manifest_hash, "predecessor_seal": previous})
        self.size += self.path.stat().st_size

    def artifact(self, value):
        raw = canonical_bytes(checked(value))
        hexdigest = hashlib.sha256(raw).hexdigest()
        name = f"inputs/{hexdigest}.json"
        if name not in self.artifacts:
            self._write(self.root / name, raw)
            self.artifacts[name] = {"path": name, "sha256": hexdigest, "bytes": len(raw)}
        return hexdigest

    def record(self, event, **payload):
        if self.closed or self.failed:
            raise ValueError("shadow_tape_unavailable")
        try:
            if canonical_bytes(SecretGuard().clean(payload)) != canonical_bytes(payload):
                raise ValueError("secret_guard_would_change_record")
            self._budget(len(canonical_bytes(payload)) + 1024)
            before = self.path.stat().st_size
            result = self.journal.record(event, **payload)
            self.size += self.path.stat().st_size - before
            self.rows += 1
            return result
        except BaseException:
            self.failed = True
            raise

    def rotate(self, at, state_digest):
        self.now = at
        if self.day != at.date() or self.path.stat().st_size >= self.manifest.segment_bytes:
            previous = self._seal("segment_boundary", state_digest)
            self.segment += 1
            self._open(previous)

    def _seal(self, reason, state_digest):
        self.record("terminal", reason=reason, state_digest=state_digest,
                    manifest_digest=self.manifest_hash)
        self.journal.close()
        raw = self.path.read_bytes()
        seal = {"schema_version": SEAL_SCHEMA, "path": self.path.name, "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw), "records": self.journal.sequence, "last_line": self.journal.previous,
                "manifest_digest": self.manifest_hash, "state_digest": state_digest}
        seal_name = f"seal-{self.segment:05d}.json"
        self._write(self.root / seal_name, canonical_bytes(seal))
        seal_hash = digest(seal)
        self.seals.append({"path": seal_name, "sha256": seal_hash})
        return seal_hash

    def close(self, reason, state_digest):
        self._seal(reason, state_digest)
        receipt = {"schema_version": RECEIPT_SCHEMA, "manifest_digest": self.manifest_hash, "seals": self.seals,
                   "artifacts": list(self.artifacts.values()), "reason": reason,
                   "state_digest": state_digest, "economics": "NOT_RUN"}
        self._write(self.root / "receipt.json", canonical_bytes(receipt))
        self.closed = True
        return digest(receipt)

    def abort(self):
        self.failed = True
        self.journal.close()  # Partial bytes remain; no repair, terminal or restart.


def verified(root, receipt_digest):
    """The caller retains the receipt hash independently, outside the tape directory."""
    root = regular_path(root)
    total = 0

    def read(name, expected):
        nonlocal total
        if not re.fullmatch(r"(?:inputs/[0-9a-f]{64}|manifest|receipt|seal-[0-9]{5})\.json", name):
            raise ValueError("unlisted_path")
        path = regular_path(root / name)
        if path.stat().st_size > 64*1024**2:
            raise ValueError("verification_file_cap")
        total += path.stat().st_size
        if total > 1024**3:
            raise ValueError("verification_byte_cap")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("artifact_digest_differs")
        value = _json(raw)
        if canonical_bytes(value) != raw:
            raise ValueError("noncanonical_artifact")
        return value

    receipt = read("receipt.json", receipt_digest)
    if receipt["schema_version"] != RECEIPT_SCHEMA:
        raise ValueError("receipt_schema")
    manifest = Manifest.restore(read("manifest.json", receipt["manifest_digest"]))
    artifacts = {}
    expected_files = {"receipt.json", "manifest.json"}
    for entry in receipt["artifacts"]:
        value = read(entry["path"], entry["sha256"])
        if len(canonical_bytes(value)) != entry["bytes"] or entry["path"] in expected_files:
            raise ValueError("artifact_manifest_differs")
        artifacts[entry["sha256"]] = decode(value)
        expected_files.add(entry["path"])
    rows, previous = [], None
    for index, entry in enumerate(receipt["seals"]):
        if entry["path"] != f"seal-{index:05d}.json":
            raise ValueError("seal_order")
        seal = read(entry["path"], entry["sha256"])
        if seal["schema_version"] != SEAL_SCHEMA:
            raise ValueError("seal_schema")
        if seal["path"] != f"quotes-{index:05d}.jsonl" or seal["manifest_digest"] != receipt["manifest_digest"]:
            raise ValueError("seal_scope")
        path = regular_path(root / seal["path"])
        if path.stat().st_size != seal["bytes"] or seal["bytes"] > 64*1024**2:
            raise ValueError("journal_size")
        total += seal["bytes"]
        if total > manifest.max_bytes:
            raise ValueError("verification_byte_cap")
        segment = verify_journal(path, expected_digest=seal["sha256"])
        if (len(segment) != seal["records"] or digest(segment[-1]) != seal["last_line"]
                or segment[0]["scope"]["predecessor_seal"] != previous
                or segment[0]["scope"]["manifest_digest"] != receipt["manifest_digest"]
                or segment[-1]["state_digest"] != seal["state_digest"]):
            raise ValueError("seal_lineage")
        rows.extend(segment)
        expected_files.update((entry["path"], seal["path"]))
        previous = entry["sha256"]
    if not rows or rows[-1]["state_digest"] != receipt["state_digest"]:
        raise ValueError("missing_terminal_state")
    for path in root.iterdir():
        regular_path(path)
        if path.is_dir() and path.name != "inputs":
            raise ValueError("unlisted_session_directory")
    for path in (root / "inputs").iterdir():
        regular_path(path)
        if not path.is_file():
            raise ValueError("unlisted_artifact_directory")
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if actual != expected_files:
        raise ValueError("unlisted_session_files")
    return manifest, tuple(rows), artifacts, receipt
