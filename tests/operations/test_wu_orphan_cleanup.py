"""Synthetic WU trees only, including native same-handle deletion on Windows."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import socket
import time

import pytest

from weather.operations.cleanup_preflight import build_cleanup_preflight, cleanup_manifest_for_paths
from weather.operations import wu_orphan_cleanup as cli
from weather.operations import wu_orphan_proofs as proofs

NOW = 200000.0
MTIME = 100000.0
REL = "wunderground/cyyz/history/day.csv.42.123.tmp"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)


class FixturePin:
    opened = set()
    removed = []

    def __init__(self, path):
        self.path = Path(path)

    def __enter__(self):
        if self.path in self.opened:
            raise OSError("busy")
        self.opened.add(self.path)
        return self

    def __exit__(self, *args):
        self.opened.remove(self.path)

    def metadata(self):
        value = self.path.stat()
        return dict(size_bytes=value.st_size, allocated_bytes=value.st_size, mtime_ns=value.st_mtime_ns,
                    device=value.st_dev, file_id=value.st_ino)

    def digest(self, *, guard):
        raw = self.path.read_bytes()
        guard.account(len(raw))
        return hashlib.sha256(raw).hexdigest()

    def remove(self):
        assert self.path in self.opened
        self.removed.append(self.path)
        self.path.unlink()


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "data"
    path = root / REL
    path.parent.mkdir(parents=True)
    path.write_bytes(b"synthetic orphan\n")
    os.utime(path, (MTIME, MTIME))
    path.with_name("day.csv").write_bytes(b"retained final\n")
    FixturePin.removed = []
    assert not FixturePin.opened
    return root, path


def observations(**kwargs):
    return dict(pin_factory=FixturePin, final_factory=FixturePin, now=lambda: NOW,
                process_reader=lambda pid: (False, None), **kwargs)


def planned(root, **changes):
    settings = observations()
    settings.update(changes)
    return cli.plan(root, **settings)


def approved(value):
    value = deepcopy(value)
    value["operator_review"] = dict(approved=True, approved_by="fixture", note="exact fixture only",
                                   plan_sha256=value["plan_sha256"])
    return value


@pytest.mark.parametrize("fault,reason", [
    ("live", "writer_not_proved_released"),
    ("reused_unknown_start", "writer_not_proved_released"),
    ("reused_old_start", "writer_not_proved_released"),
    ("future_start", "writer_not_proved_released"),
    ("unknown", "writer_not_proved_released"),
    ("recent", "age_not_over_24_hours"),
    ("exactly_24h", "age_not_over_24_hours"),
    ("missing_final", "final_sibling_unavailable"),
    ("open_handle", "exclusive_handle_or_file_unavailable"),
])
def test_each_missing_proof_refuses(tree, fault, reason):
    root, path = tree
    args = {}
    identities = dict(live=(True, MTIME - 1), reused_unknown_start=(True, None),
                      reused_old_start=(True, MTIME), future_start=(True, NOW + 1), unknown=(None, None))
    if fault in identities:
        args["process_reader"] = lambda _: identities[fault]
    elif fault in {"recent", "exactly_24h"}:
        stamp = NOW if fault == "recent" else NOW - 86400
        os.utime(path, (stamp, stamp))
    elif fault == "missing_final":
        path.with_name("day.csv").unlink()
    else:
        FixturePin.opened.add(path)
    try:
        manifest = planned(root, **args)
        assert not manifest["candidates"]
        assert manifest["refused"][0]["reason"] == reason
        assert path.exists() and not FixturePin.removed
    finally:
        FixturePin.opened.discard(path)


def test_proven_later_starting_pid_is_allowed_per_owner(tree):
    root, _ = tree
    value = planned(root, process_reader=lambda _: (True, MTIME + 1))
    assert len(value["candidates"]) == 1
    assert value["candidates"][0]["wu_orphan_proof"]["writer_started_at"] == MTIME + 1


def test_plan_preflight_apply_receipts_and_source_retention(tree, tmp_path):
    root, path = tree
    manifest = approved(planned(root))
    before = path.with_name("day.csv").read_bytes()
    preflight = tmp_path / "preflight"
    preflight.mkdir()
    assert cli.execute(manifest, root, preflight, **observations())["status"] == "PASS"
    assert path.exists() and not FixturePin.removed
    out = tmp_path / "apply"
    out.mkdir()
    result = cli.execute(manifest, root, out, apply=True, **observations())
    assert result["status"] == "PASS" and result["results"][0]["deleted"]
    assert not path.exists() and path.with_name("day.csv").read_bytes() == before
    assert len(list(out.glob("*-intent.json"))) == len(list(out.glob("*-receipt.json"))) == 1
    assert not FixturePin.opened


@pytest.mark.parametrize("fault", ["hash", "mtime", "final", "pid", "unreviewed", "review_hash", "self_hash", "forged_proof"])
def test_changed_or_unbound_manifest_cannot_delete(tree, tmp_path, fault):
    root, path = tree
    manifest = approved(planned(root))
    args = observations()
    if fault == "hash":
        path.write_bytes(b"altered orphan!!\n")
        os.utime(path, (MTIME, MTIME))
    elif fault == "mtime":
        os.utime(path, (MTIME + 1, MTIME + 1))
    elif fault == "final":
        path.with_name("day.csv").write_bytes(b"changed")
    elif fault == "pid":
        args["process_reader"] = lambda _: (True, MTIME - 1)
    elif fault == "unreviewed":
        manifest["operator_review"]["approved"] = False
    elif fault == "review_hash":
        manifest["operator_review"]["plan_sha256"] = "0" * 64
    elif fault == "self_hash":
        manifest["candidates"][0]["sha256"] = "0" * 64
    else:
        manifest["candidates"][0]["wu_orphan_proof"]["no_open_handle"] = False
        manifest["plan_sha256"] = cli.plan_hash(manifest)
        manifest = approved(manifest)
    out = tmp_path / "attempt"
    out.mkdir()
    if fault in {"unreviewed", "review_hash", "self_hash"}:
        with pytest.raises(proofs.OrphanRefused):
            cli.execute(manifest, root, out, apply=True, **args)
    else:
        assert cli.execute(manifest, root, out, apply=True, **args)["status"] == "BLOCK"
    assert path.exists() and not FixturePin.removed


def test_recheck_after_intent_before_remove(tree, tmp_path, monkeypatch):
    root, path = tree
    manifest = approved(planned(root))
    real_write = cli._write
    alive = False
    def write(path, value):
        nonlocal alive
        real_write(path, value)
        if path.name.endswith("intent.json"):
            alive = True
    monkeypatch.setattr(cli, "_write", write)
    args = observations()
    args["process_reader"] = lambda _: (alive, MTIME - 1 if alive else None)
    out = tmp_path / "apply"
    out.mkdir()
    result = cli.execute(manifest, root, out, apply=True, **args)
    assert result["status"] == "BLOCK" and path.exists()
    assert "writer_not_proved_released" in result["results"][0]["reason"]
    assert not FixturePin.removed


def test_caps_close_handles_and_write_no_sources(tree):
    root, path = tree
    manifest = cli.plan(root, max_bytes=1, **observations())
    assert manifest["stop_reason"] == "byte_cap" and not manifest["candidates"]
    assert manifest["bytes_read"] == 0 and path.exists() and not FixturePin.opened
    manifest = cli.plan(root, max_entries=1, **observations())
    assert manifest["stop_reason"] == "entry_cap" and manifest["visited_entries"] == 1
    times = iter([0, 2])
    budget = proofs.Budget(100, 1, clock=lambda: next(times))
    with pytest.raises(proofs.OrphanRefused, match="time_cap"):
        budget.admit()


def test_generic_cleanup_cannot_bypass_missing_wu_proof(tree):
    root, path = tree
    manifest = cleanup_manifest_for_paths([path], root=root, deletion_reason="fixture",
        operator_review=dict(approved=True, approved_by="fixture", note="fixture"))
    for target_root, relative in ((root, REL), (path.parent, path.name)):
        forged = deepcopy(manifest)
        forged["candidates"][0].update(path=relative, data_path="snapshots/x/snapshots.jsonl")
        result = build_cleanup_preflight(forged, root=target_root)
        assert result["status"] == "BLOCK"
        assert any(c["check"] == "wu_orphan_current_proofs" and c["status"] == "BLOCK"
                   for c in result["candidates"][0]["checks"])


def test_native_current_process_identity():
    if os.name != "nt":
        pytest.skip("native Windows process proof")
    alive, started = proofs.writer_identity(os.getpid())
    assert alive and started <= time.time() and started > 0
    # A missing PID is distinguishable from access-denied/unknown.
    assert proofs.writer_identity(0xFFFFFFFF) == (False, None)


@pytest.mark.skipif(os.name != "nt", reason="native NTFS fixture")
def test_native_exclusive_handle_and_same_handle_delete(tmp_path):
    root = tmp_path / "data"
    path = root / f"wunderground/cyyz/day.csv.{os.getpid()}.123.tmp"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"synthetic temp")
    final = path.with_name("day.csv")
    final.write_bytes(b"synthetic final")
    old = time.time() - 90000
    os.utime(path, (old, old))
    with path.open("rb"):
        blocked = cli.plan(root)
        assert not blocked["candidates"] and blocked["refused"]
    manifest = approved(cli.plan(root))
    assert len(manifest["candidates"]) == 1
    # Standalone generic preflight must acquire fresh native proofs itself.
    assert build_cleanup_preflight(manifest, root=root)["status"] == "PASS"
    out = tmp_path / "out"
    out.mkdir()
    result = cli.execute(manifest, root, out, apply=True)
    assert result["status"] == "PASS", result
    assert not path.exists() and final.read_bytes() == b"synthetic final"


@pytest.mark.skipif(os.name != "nt", reason="native NTFS fixture")
def test_native_hardlinked_temp_stays_protected(tmp_path):
    root = tmp_path / "data"
    path = root / f"wunderground/cyyz/day.csv.{os.getpid()}.123.tmp"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"fixture shared inode")
    path.with_name("day.csv").write_bytes(b"fixture final")
    os.link(path, tmp_path / "second-link")
    old = time.time() - 90000
    os.utime(path, (old, old))
    value = cli.plan(root)
    assert not value["candidates"] and value["refused"]
    assert path.exists() and (tmp_path / "second-link").exists()


@pytest.mark.parametrize("relative", ["../elsewhere.42.1.tmp", "wunderground/cyyz/../x.42.1.tmp",
    "wunderground/cyyz/x:stream.42.1.tmp", "snapshots/cyyz/x.42.1.tmp", "wunderground/cyyz/random.tmp"])
def test_path_scope_refused(tree, relative):
    with pytest.raises((ValueError, OSError)):
        proofs.candidate_path(tree[0], relative)


def test_cli_requires_new_output_and_exact_manifest_hash(tree, tmp_path, monkeypatch, capsys):
    root, path = tree
    manifest = approved(planned(root))
    source = tmp_path / "review.json"
    source.write_text(json.dumps(manifest))
    monkeypatch.setattr(cli, "observe", lambda *a, **kw: proofs.observe(*a, **{**kw, **observations()}))
    args = ["preflight", "--root", str(root), "--output", str(tmp_path / "out"), "--manifest", str(source),
            "--manifest-sha256", hashlib.sha256(source.read_bytes()).hexdigest()]
    assert cli.main(args) == 0
    assert cli.main(args) == 2  # Existing attempts are immutable.
    assert path.exists()
    args[args.index("--output") + 1] = str(tmp_path / "bad-hash")
    args[-1] = "0" * 64
    assert cli.main(args) == 2 and path.exists()
    assert not FixturePin.removed
