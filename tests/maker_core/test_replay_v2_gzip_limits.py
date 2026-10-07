"""Maker replay v2 X1: bundle v0.3 gzip streams and the v2 byte AND time limits (fictional rows only).

Owner decisions 8 and 9; B-def D1 (time across re-reads), D2 (gzip reader), D3 (determinism).
"""
from datetime import date
import gzip
import hashlib
import json
import time
import zlib

import pytest

from maker_core.evidence.journal import canonical_bytes
from maker_core.replay.bundle import HOST_MAX_BYTES, Bundle, BundleError, Limits, sha256
from maker_core.replay.bundle_v02 import FORMAT_V02, FORMAT_V03, load_any, open_stream_bundle
from maker_core.replay.v2 import gzip_stream
from maker_core.replay.v2.compaction import expand, row as plain_row
from maker_core.replay.v2.limits import (CEILING_PASS_SECONDS, CEILING_RUN_SECONDS, GIB, RunBudget, V2Limits,
                                         coerce)
from maker_core.replay.v2.writer import BundleWriter, validate
from tests.maker_core.test_replay_v2_writer import Day
from tools.research.maker_replay_v2.fixture170 import Day as Day170
from tools.research.maker_replay_v2.run import write_forms

CANONICAL_HEADER_LEVEL_6 = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xff"


def _write(folder, day, **kwargs):
    writer = BundleWriter(folder, spill_bytes=512, **kwargs)
    for value in day.rows:
        writer.add(value, canonical_bytes(value))
    return writer.finish(day.manifest(), day.groups)


@pytest.fixture
def bundle(tmp_path):
    day = Day()
    written = _write(tmp_path / "bundle", day)
    return tmp_path / "bundle", written


def _manifest(folder):
    return json.loads((folder / "bundle.json").read_bytes())


def _replace_stream(folder, name, stored, *, decoded=None, fix_manifest=True):
    """Write new stored bytes for one stream; optionally re-bind the manifest's stored (and decoded) fields."""
    (folder / name).write_bytes(stored)
    if not fix_manifest:
        return
    manifest = _manifest(folder)
    for entry in manifest["streams"]:
        if entry["path"] == name:
            entry.update(sha256=sha256(stored), bytes=len(stored))
            if decoded is not None:
                entry.update(decoded_sha256=sha256(decoded), decoded_bytes=len(decoded),
                             records=decoded.count(b"\n"))
    (folder / "bundle.json").write_bytes(canonical_bytes(manifest))


def _expanded(folder, **kwargs):
    opened = open_stream_bundle(folder, **kwargs)
    return [canonical_bytes(plain_row(r)) for r in expand(opened.records(), opened.coverage_groups)]


# --- Round trip and determinism (D3) ---------------------------------------------------------------------


def test_gzip_round_trip_is_byte_identical_across_two_writes_and_binds_decoded_hashes(tmp_path, monkeypatch):
    day = Day()
    clock = iter([1_000_000_000.0, 2_000_000_000.0])
    real = time.time
    # A wall clock that moves between the two writes: the mutant "mtime not pinned" changes the header.
    monkeypatch.setattr(gzip.time, "time", lambda: next(clock, real()))
    first = _write(tmp_path / "one", day)
    second = _write(tmp_path / "two", day)
    plain = _write(tmp_path / "plain", day, compress=False)
    one, two = tmp_path / "one", tmp_path / "two"
    assert sorted(p.name for p in one.iterdir()) == sorted(p.name for p in two.iterdir())
    for path in one.iterdir():
        assert path.read_bytes() == (two / path.name).read_bytes(), path.name
    manifest = _manifest(one)
    assert manifest["format"] == FORMAT_V03 and _manifest(tmp_path / "plain")["format"] == FORMAT_V02
    assert manifest["compression"] == dict(codec="gzip", level=6, mtime=0,
                                           zlib_runtime_version=zlib.ZLIB_RUNTIME_VERSION)
    assert first["compression"]["python"] and first["compression"]["zlib_version"] == zlib.ZLIB_VERSION
    for entry in manifest["streams"]:
        kind = entry["path"].removesuffix(".jsonl.gz")
        raw = (one / entry["path"]).read_bytes()
        assert raw[:10] == CANONICAL_HEADER_LEVEL_6
        decoded = gzip.decompress(raw)
        plain_bytes = (tmp_path / "plain" / f"{kind}.jsonl").read_bytes()
        # The decoded identity is the plain v0.2 stream's identity: portable across zlib builds.
        assert decoded == plain_bytes
        assert entry["decoded_sha256"] == sha256(decoded) == plain["streams"][kind]["sha256"]
        assert entry["decoded_bytes"] == len(decoded) and entry["records"] == decoded.count(b"\n")
        assert entry["sha256"] == sha256(raw) and entry["bytes"] == len(raw)
        assert first["streams"][kind]["decoded_sha256"] == second["streams"][kind]["decoded_sha256"]
    opened = open_stream_bundle(one)
    assert dict(opened.decoded_hashes) == {e["path"]: e["decoded_sha256"] for e in manifest["streams"]}
    assert {r.encoding for r in opened.streams} == {"gzip"}
    assert _expanded(one) == _expanded(tmp_path / "plain")
    assert validate(one, first["v01"])["kinds"] == validate(tmp_path / "plain", plain["v01"])["kinds"]
    assert first["v01"] == plain["v01"]


def test_compressed_header_does_not_carry_the_target_file_name(tmp_path):
    source = tmp_path / "rows.jsonl"
    source.write_bytes(b"".join(canonical_bytes(dict(n=n)) for n in range(500)))
    a = gzip_stream.compress_file(source, tmp_path / "alpha.jsonl.gz")
    b = gzip_stream.compress_file(source, tmp_path / "a-much-longer-name.jsonl.gz")
    assert a == b
    assert (tmp_path / "alpha.jsonl.gz").read_bytes() == (tmp_path / "a-much-longer-name.jsonl.gz").read_bytes()
    with pytest.raises(BundleError, match="invalid_compression_level"):
        gzip_stream.compress_file(source, tmp_path / "x.gz", level=0)


# --- Decompression bomb (D2.2) ---------------------------------------------------------------------------


def test_a_decompression_bomb_is_refused_before_it_inflates_past_the_declared_size():
    bomb = gzip.compress(b"\n" * (256 * 1024**2), mtime=0)  # 256 MiB of newlines in about 250 KB
    assert len(bomb) < 1024**2
    produced = 0
    with pytest.raises(BundleError, match="stream_decoded_size_mismatch"):
        for block in gzip_stream.decode([bomb[i:i + 65536] for i in range(0, len(bomb), 65536)], 1024**2):
            produced += len(block)
    assert produced <= 1024**2  # nothing past the declared size is ever handed out


def test_bundle_refuses_a_stream_that_inflates_past_its_manifest_size(bundle):
    folder, _ = bundle
    decoded = gzip.decompress((folder / "book.jsonl.gz").read_bytes())
    swollen = decoded + decoded[-200:] * 50_000  # same tail line repeated: far more decoded bytes
    _replace_stream(folder, "book.jsonl.gz", gzip.compress(swollen, mtime=0))  # stored fields only re-bound
    with pytest.raises(BundleError, match="stream_decoded_size_mismatch"):
        open_stream_bundle(folder)


def test_declared_decoded_sizes_are_bounded_before_any_inflation(bundle):
    folder, _ = bundle
    manifest = _manifest(folder)
    manifest["streams"][0]["decoded_bytes"] = manifest["streams"][0]["records"] * 1024**2 + 1
    (folder / "bundle.json").write_bytes(canonical_bytes(manifest))
    with pytest.raises(BundleError, match="stream_decoded_size_unbounded"):
        open_stream_bundle(folder)


def test_bundle_decoded_byte_cap_is_its_own_limit(bundle):
    folder, _ = bundle
    total = sum(e["decoded_bytes"] for e in _manifest(folder)["streams"])
    open_stream_bundle(folder, limits=V2Limits(max_bundle_decoded_bytes=total))
    with pytest.raises(BundleError, match="decoded_byte_cap"):
        open_stream_bundle(folder, limits=V2Limits(max_bundle_decoded_bytes=total - 1))


# --- Corruption and multi-member streams (D2.3) ----------------------------------------------------------


def _flip(raw, index):
    data = bytearray(raw)
    data[index] ^= 0x01
    return bytes(data)


@pytest.mark.parametrize("fault, code", [
    ("bad_magic", "stream_decompression_failed"),
    ("crc32", "stream_decompression_failed"),
    ("isize", "stream_decompression_failed"),
    ("truncated", "stream_decompression_failed"),
    ("deflate_body", "stream_decompression_failed|stream_decoded_size_mismatch"),
    ("named_header", "stream_gzip_header_not_canonical"),
    ("timestamped_header", "stream_gzip_header_not_canonical"),
])
def test_corrupt_gzip_is_a_bundle_error_never_a_zlib_or_eof_error(bundle, fault, code):
    folder, _ = bundle
    raw = (folder / "book.jsonl.gz").read_bytes()
    decoded = gzip.decompress(raw)
    bad = {
        "bad_magic": lambda: b"\x1f\x8c" + raw[2:],
        "crc32": lambda: _flip(raw, len(raw) - 8),
        "isize": lambda: _flip(raw, len(raw) - 2),
        "truncated": lambda: raw[:-4],
        "deflate_body": lambda: _flip(raw, len(raw) // 2),
        "named_header": lambda: _named(decoded),
        "timestamped_header": lambda: gzip.compress(decoded, mtime=1_700_000_000),
    }[fault]()
    _replace_stream(folder, "book.jsonl.gz", bad)  # the manifest binds the corrupt bytes: only gzip can refuse
    with pytest.raises(BundleError, match=code):
        open_stream_bundle(folder)


def _named(decoded):
    import io
    out = io.BytesIO()
    with gzip.GzipFile(filename="book.jsonl", mode="wb", fileobj=out, mtime=0) as handle:
        handle.write(decoded)
    return out.getvalue()


def test_changed_stored_bytes_without_a_rebound_manifest_are_refused(bundle):
    folder, _ = bundle
    raw = (folder / "book.jsonl.gz").read_bytes()
    _replace_stream(folder, "book.jsonl.gz", _flip(raw, len(raw) - 8), fix_manifest=False)
    with pytest.raises(BundleError, match="stream_hash_or_size_mismatch|stream_decompression_failed"):
        open_stream_bundle(folder)


@pytest.mark.parametrize("tail", ["second_member", "empty_member", "trailing_zero"])
def test_a_multi_member_or_trailing_stream_is_refused(bundle, tail):
    folder, _ = bundle
    raw = (folder / "book.jsonl.gz").read_bytes()
    decoded = gzip.decompress(raw)
    extra = {"second_member": gzip.compress(decoded[-300:][decoded[-300:].index(b"\n") + 1:], mtime=0),
             "empty_member": gzip.compress(b"", mtime=0), "trailing_zero": b"\x00"}[tail]
    # Python's gzip silently concatenates members; the v0.3 reader must not.
    if tail != "trailing_zero":
        assert gzip.decompress(raw + extra).startswith(decoded)
    _replace_stream(folder, "book.jsonl.gz", raw + extra)
    with pytest.raises(BundleError, match="stream_multi_member_or_trailing_data"):
        open_stream_bundle(folder)


def test_pass_two_refuses_a_stream_swapped_after_pass_one(bundle):
    folder, _ = bundle
    opened = open_stream_bundle(folder)
    raw = (folder / "book.jsonl.gz").read_bytes()
    (folder / "book.jsonl.gz").write_bytes(_flip(raw, len(raw) - 8))
    with pytest.raises(BundleError, match="input_changed_between_passes|stream_decompression_failed"):
        list(opened.records())


def test_v03_manifest_shape_is_exact(bundle):
    folder, _ = bundle
    good = (folder / "bundle.json").read_bytes()
    for edit, code in (
            (lambda m: m["streams"][0].pop("decoded_sha256"), "unexpected_fields"),
            (lambda m: m.pop("compression"), "unexpected_fields"),
            (lambda m: m["compression"].update(mtime=5), "unsupported_compression"),
            (lambda m: m["compression"].update(codec="zstd"), "unsupported_compression"),
            (lambda m: m["streams"][0].update(path=m["streams"][0]["path"].removesuffix(".gz")),
             "invalid_or_duplicate_stream_path"),
            (lambda m: m.update(format=FORMAT_V02), "unexpected_fields")):
        manifest = json.loads(good)
        edit(manifest)
        (folder / "bundle.json").write_bytes(canonical_bytes(manifest))
        with pytest.raises(BundleError, match=code):
            open_stream_bundle(folder)
    (folder / "bundle.json").write_bytes(good)
    open_stream_bundle(folder)


# --- Limits: time across re-reads (D1) and bytes (decision 9) --------------------------------------------


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_records_can_be_reread_after_the_pass_one_time_cap(bundle):
    folder, _ = bundle
    clock = Clock()
    opened = open_stream_bundle(folder, limits=V2Limits(max_pass_seconds=100.0), clock=clock)
    first = list(opened.records())
    clock.now += 14_400 + 3_200  # beyond the frozen reader's 4 h clock started at the first open
    assert list(opened.records()) == first  # a fresh pass clock per re-read
    # Inside one pass, the pass budget still binds.
    records = opened.records()
    next(records)
    clock.now += 100.0
    with pytest.raises(BundleError, match="time_cap"):
        list(records)


def test_an_elapsed_run_deadline_refuses_every_pass(bundle):
    folder, _ = bundle
    clock = Clock()
    run = RunBudget(max_run_seconds=500.0, clock=clock)
    opened = open_stream_bundle(folder, limits=V2Limits(max_pass_seconds=400.0), clock=clock, run=run)
    clock.now = 300.0
    list(opened.records())
    clock.now = 500.0  # each pass would be fresh, but the run is over
    with pytest.raises(BundleError, match="run_time_cap"):
        list(opened.records())
    with pytest.raises(BundleError, match="run_time_cap"):
        open_stream_bundle(folder, clock=clock, run=run)


def test_a_sixteen_date_look_of_17600_seconds_with_clock_rounds_fits_the_run_budget(bundle):
    # B-def D1: 16 dates x ~1,100 s, re-read by 1 base drive plus clock rounds; the frozen 14,400 s cap failed.
    folder, _ = bundle
    clock = Clock()
    run = RunBudget(clock=clock)
    dates = [open_stream_bundle(folder, limits=V2Limits(max_pass_seconds=2_048.0), clock=clock, run=run)
             for _ in range(16)]
    for _ in range(1 + 2):  # base passes, then two matched-clock rounds
        for opened in dates:
            for _ in opened.records():
                pass
            clock.now += 1_100 / 3
    assert 14_400 < clock.now < CEILING_RUN_SECONDS
    assert run.stored_bytes == 16 * dates[0].input_bytes  # charged per open, never per re-read
    clock.now = CEILING_RUN_SECONDS
    with pytest.raises(BundleError, match="run_time_cap"):
        list(dates[0].records())


def test_v2_limits_admit_sixteen_dates_of_one_gib_and_refuse_seventeen():
    run = RunBudget(clock=lambda: 0.0)
    for _ in range(16):
        run.charge(GIB)
    with pytest.raises(BundleError, match="run_input_byte_cap"):
        run.charge(1)
    amended = RunBudget(max_run_stored_bytes=32 * GIB, clock=lambda: 0.0)
    for _ in range(16):
        amended.charge(2 * GIB)
    with pytest.raises(BundleError, match="run_input_byte_cap"):
        amended.charge(1)


def test_limits_refuse_values_above_their_ceilings_and_keep_frozen_meaning():
    with pytest.raises(BundleError, match="invalid_time_limit"):
        V2Limits(max_pass_seconds=CEILING_PASS_SECONDS + 1)
    with pytest.raises(BundleError, match="invalid_time_limit"):
        RunBudget(max_run_seconds=CEILING_RUN_SECONDS + 1)
    with pytest.raises(BundleError, match="invalid_or_unbounded_limit"):
        RunBudget(max_run_stored_bytes=32 * GIB + 1)
    with pytest.raises(BundleError, match="invalid_or_unbounded_limit"):
        V2Limits(max_bundle_stored_bytes=0)
    with pytest.raises(BundleError, match="invalid_time_limit"):
        V2Limits(max_pass_seconds=True)
    frozen = Limits(2**30, 10**6, 300)
    assert coerce(frozen) == V2Limits(2**30, 2**30, 10**6, 300.0)
    assert coerce(None) == V2Limits()
    assert V2Limits(max_bundle_stored_bytes=16 * GIB).frozen().max_bytes == HOST_MAX_BYTES


def test_bundle_stored_byte_cap_and_run_byte_cap_refuse_before_reading(bundle):
    folder, _ = bundle
    stored = open_stream_bundle(folder).input_bytes
    open_stream_bundle(folder, limits=V2Limits(max_bundle_stored_bytes=stored))
    with pytest.raises(BundleError, match="input_byte_cap_or_size_mismatch"):
        open_stream_bundle(folder, limits=V2Limits(max_bundle_stored_bytes=stored - 1))
    run = RunBudget(max_run_stored_bytes=stored * 2 - 1, clock=lambda: 0.0)
    open_stream_bundle(folder, run=run)
    with pytest.raises(BundleError, match="run_input_byte_cap"):
        open_stream_bundle(folder, run=run)


def test_load_any_applies_v2_limits_and_the_run_budget_to_every_format(tmp_path, bundle):
    folder, _ = bundle
    run = RunBudget(clock=lambda: 0.0)
    opened = load_any(folder, limits=V2Limits(), run=run)
    assert opened.format == FORMAT_V03 and run.stored_bytes == opened.input_bytes
    forms = write_forms(Day170(date(2026, 9, 27), union=60, trades=50, start_minute=230, minutes=5), tmp_path / "f")
    frozen = load_any(forms["v01"], limits=V2Limits(max_pass_seconds=60.0), run=run)
    assert isinstance(frozen, Bundle) and run.stored_bytes == opened.input_bytes + frozen.input_bytes
    with pytest.raises(BundleError, match="run_time_cap"):
        load_any(forms["v01"], run=RunBudget(max_run_seconds=1.0, clock=iter([0.0, 5.0]).__next__))


def test_frozen_limits_still_bind_v03_like_v02(bundle):
    folder, _ = bundle
    stored = open_stream_bundle(folder).input_bytes
    with pytest.raises(BundleError):
        open_stream_bundle(folder, limits=Limits(stored - 1, 10**6, 300))
    decoded = sum(e["decoded_bytes"] for e in _manifest(folder)["streams"])
    # A frozen byte cap bounds decoded bytes too: it meant "bytes processed" for plain streams.
    with pytest.raises(BundleError, match="decoded_byte_cap|input_byte_cap"):
        open_stream_bundle(folder, limits=Limits(max(stored, decoded - 1), 10**6, 300))
    assert hashlib.sha256((folder / "bundle.json").read_bytes()).hexdigest() == open_stream_bundle(
        folder, limits=Limits(2**30, 10**6, 300)).input_hashes["bundle.json"]
