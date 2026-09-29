"""Bounded, create-only execution-pack IO. All paths are explicit caller inputs."""
import os
from pathlib import Path
import time

from maker_core.evidence.journal import canonical_bytes
from maker_core.replay.bundle import BundleError, Limits, _Reader, _json, load_bundle, regular_path, sha256


def read_json(path, maximum=1024**2):
    raw = _Reader(Limits(maximum, 1, 5), time.monotonic).read(path, maximum)
    return _json(raw), sha256(raw)


def write_json(path, value, maximum=8*1024**2):
    raw = canonical_bytes(value)
    if len(raw) > maximum:
        raise BundleError("output_byte_cap")
    path = regular_path(path)
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return sha256(raw)


def load_days(paths, limits, check, *, now):
    if not 1 <= len(paths) <= 15 or len(set(map(lambda p: str(Path(p).absolute()), paths))) != len(paths):
        raise BundleError("invalid_bundle_inventory")
    bundles, remaining_bytes, remaining_records = [], limits.max_bytes, limits.max_records
    for path in paths:
        check()
        bundle = load_bundle(path, limits=Limits(remaining_bytes, remaining_records, limits.max_seconds))
        if bundle.sealed_at > now or bundle.day >= now.date():
            raise BundleError("bundle_not_closed_now")
        remaining_bytes -= bundle.input_bytes
        remaining_records -= len(bundle.records)
        bundles.append(bundle)
    if len({b.day for b in bundles}) != len(bundles):
        raise BundleError("duplicate_bundle_day")
    check()
    return tuple(sorted(bundles, key=lambda b: b.day))


def deadline(seconds):
    started = time.monotonic()

    def check():
        if time.monotonic() - started >= seconds:
            raise BundleError("time_cap")
    return check
