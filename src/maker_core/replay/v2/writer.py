"""Bundle v0.2 streaming writer and streaming validation (maker replay v2 W2, registration draft §6).

The exporter pushes v0.1 rows in its own sequence order. Nothing whole-output is held in memory:

- **Sorted streams.** Each kind is one stream sorted by ``(captured_at, sequence)``.
  A kind that arrives in order is written straight to disk. A kind that breaks order (plugin inputs
  keep their original capture clock, ledger settlements their later record clock) spills bounded
  sorted runs and is merged once at the end.
- **Coverage.** Coverage rows go to a compact disk spool, one line per exporter run (condition
  index, payload and source table), with a marker for each condition's first descriptor. Groups
  are only known at the end of the day, so ``finish`` replays the spool through the W1
  ``Compactor`` under the final groups. The same-coverage refusal (``coverage_group_mismatch``)
  is the Compactor's. No duplicate elision is added: the exporter already drops repeats.
- **Compression (format v0.3, the default; owner decision 8).** Each finished stream is gzipped once at
  ``finish`` into ``<kind>.jsonl.gz`` (``v2.gzip_stream``: ``mtime=0``, empty header name, fixed level), so
  the transient disk peak is about decoded plus stored bytes. The manifest binds stored ``sha256``/``bytes``
  and the decoded ``decoded_sha256``/``decoded_bytes``/``records``; the decoded SHA-256 is the cross-host
  identity, because stored bytes depend on the zlib build. ``compress=False`` writes plain v0.2
  ``<kind>.jsonl`` streams. ``max_stream_bytes`` bounds DECODED bytes while writing; the exporter checks
  stored bytes against its output cap after ``finish``.
- **Validation** (``validate``) re-reads the written bundle through the two-pass stream reader
  and ``expand``, and needs the expanded rows' order-independent sum hash, count and bytes to
  equal those of the v0.1 rows pushed. ``v01`` is also the SHA-256 the v0.1 exporter would have
  written for ``events.jsonl`` (sequence order), so E3 can compare an existing v0.1 export by hash.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
import hashlib
import heapq
import json
from pathlib import Path
import shutil

from maker_core.evidence.journal import canonical_bytes
from maker_core.replay.bundle import BundleError, Limits, sha256, timestamp
from maker_core.replay.bundle_v02 import FORMAT_V02, FORMAT_V03, GROUPED_FORMATS, open_stream_bundle
from maker_core.replay.v2 import gzip_stream
from maker_core.replay.v2.compaction import Compactor, expand, row as plain_row

SPILL_BYTES = 32 * 1024**2
MAX_RUNS = 256
MOD = 2**256
WORK = "_work"
FORMAT_LABELS = {FORMAT_V02: "v0.2", FORMAT_V03: "v0.3"}


def row_hash(raw: bytes) -> int:
    """One row's contribution to the order-independent sum hash."""
    return int.from_bytes(hashlib.sha256(raw).digest(), "big")


class Digest:
    """Sequence-order SHA-256, bytes and count, plus an order-independent sum of row hashes."""

    def __init__(self):
        self.sha, self.bytes, self.records, self.sum = hashlib.sha256(), 0, 0, 0

    def update(self, raw: bytes):
        self.sha.update(raw)
        self.bytes += len(raw)
        self.records += 1
        self.sum = (self.sum + row_hash(raw)) % MOD

    def result(self) -> dict:
        return dict(sha256=self.sha.hexdigest(), bytes=self.bytes, records=self.records, sum256=f"{self.sum:064x}")


class _File:
    def __init__(self, path: Path):
        self.path, self.handle, self.digest = path, path.open("xb"), Digest()

    def write(self, raw: bytes):
        self.handle.write(raw)
        self.digest.update(raw)

    def close(self) -> dict:
        self.handle.close()
        return self.digest.result()


def _line_key(line: bytes):
    value = json.loads(line)
    return timestamp(value["captured_at"]), value["sequence"]


class SortedStream:
    """One kind's stream: in-order rows go straight to disk; after the first order break, rows spill
    sorted runs of at most ``spill_bytes`` and are merged at ``finish``."""

    def __init__(self, work: Path, kind: str, spill_bytes: int = SPILL_BYTES):
        self.work, self.kind, self.spill_bytes = work, kind, spill_bytes
        self.head, self.last = _File(work / f"{kind}.run0"), None
        self.buffer, self.buffered, self.runs = [], 0, []
        self.spilled_runs, self.merging = 0, None

    def close(self):
        for file in (self.head, self.merging):
            if file is not None and not file.handle.closed:
                file.handle.close()

    def add(self, key: tuple, raw: bytes):
        if not self.runs and not self.buffer and (self.last is None or key > self.last):
            self.head.write(raw)
            self.last = key
            return
        self.buffer.append((key, raw))
        self.buffered += len(raw)
        if self.buffered >= self.spill_bytes:
            self._spill()

    def _spill(self):
        if len(self.runs) >= MAX_RUNS:
            raise BundleError("sort_run_cap")
        self.buffer.sort(key=lambda item: item[0])
        path = self.work / f"{self.kind}.run{len(self.runs) + 1}"
        with path.open("xb") as handle:
            for _, raw in self.buffer:
                handle.write(raw)
        self.runs.append(path)
        self.buffer, self.buffered = [], 0
        self.spilled_runs += 1

    def finish(self, final: Path) -> dict:
        head = self.head.close()
        if not self.runs and not self.buffer:
            self.head.path.rename(final)
            return head
        if self.buffer:
            self._spill()
        out, last = _File(final), None
        self.merging = out
        handles = [path.open("rb") for path in (self.head.path, *self.runs)]
        try:
            lines = [((_line_key(line), line) for line in handle) for handle in handles]
            for key, line in heapq.merge(*lines, key=lambda item: item[0]):
                if last is not None and key <= last:
                    raise BundleError("duplicate_sorted_record")
                last = key
                out.write(line)
        finally:
            for handle in handles:
                handle.close()
        return out.close()


class BundleWriter:
    """Push v0.1 rows (dict plus canonical bytes) in sequence order; ``finish`` writes the v0.2 bundle."""

    def __init__(self, folder: Path, *, spill_bytes: int = SPILL_BYTES, max_stream_bytes: int | None = None,
                 compress: bool = True, level: int = gzip_stream.LEVEL):
        if compress and (type(level) is not int or not 1 <= level <= 9):
            raise BundleError("invalid_compression_level")
        self.compress, self.level = compress, level
        self.format = FORMAT_V03 if compress else FORMAT_V02
        self.folder, self.work = folder, folder / WORK
        self.work.mkdir(parents=True)
        self.spill_bytes, self.max_stream_bytes = spill_bytes, max_stream_bytes
        self.streams, self.v01 = {}, Digest()
        self.kind_bytes, self.kind_records = Counter(), Counter()
        self.spool = (self.work / "coverage.spool").open("xb")
        self.index, self.names, self.described = {}, [], set()
        self.run, self.covered = None, set()
        self.stream_bytes = 0

    def _cid(self, cid):
        if cid not in self.index:
            self.index[cid] = len(self.names)
            self.names.append(cid)
        return self.index[cid]

    def add(self, row: Mapping, raw: bytes):
        """``row`` is the exporter's v0.1 row with ``captured_at`` as ISO text; ``raw`` its canonical bytes."""
        self.v01.update(raw)
        kind, cid = row["kind"], row["condition_id"]
        self.kind_records[kind] += 1
        self.kind_bytes[kind] += len(raw)
        if kind == "coverage":
            self._coverage(row)
            return
        self._end_run()
        if kind == "descriptor" and cid not in self.described:
            self.described.add(cid)
            self.spool.write(canonical_bytes(dict(d=self._cid(cid))))
        stream = self.streams.get(kind)
        if stream is None:
            stream = self.streams[kind] = SortedStream(self.work, kind, self.spill_bytes)
        stream.add((timestamp(row["captured_at"]), row["sequence"]), raw)
        self.stream_bytes += len(raw)
        if self.max_stream_bytes is not None and self.stream_bytes > self.max_stream_bytes:
            raise BundleError("bundle_output_cap")

    def _coverage(self, row):
        run = self.run
        if run is not None and (run["at"] != row["captured_at"] or run["last"] >= row["condition_id"]
                                or run["next"] != row["sequence"]):
            self._end_run()
            run = None
        if run is None:
            run = self.run = dict(at=row["captured_at"], seq=row["sequence"], next=row["sequence"], last="",
                                  rows=[], payloads={}, sources={})
        payload = run["payloads"].setdefault(row["payload_sha256"], (len(run["payloads"]), row["payload"]))[0]
        key = json.dumps(row["source_hashes"], sort_keys=True)
        source = run["sources"].setdefault(key, (len(run["sources"]), row["source_hashes"]))[0]
        run["rows"].append([self._cid(row["condition_id"]), payload, source])
        run["last"], run["next"] = row["condition_id"], row["sequence"] + 1
        self.covered.add(row["condition_id"])

    def _end_run(self):
        run, self.run = self.run, None
        if run is None:
            return
        payloads = [[h, p] for h, (_, p) in sorted(run["payloads"].items(), key=lambda item: item[1][0])]
        sources = [s for _, (_, s) in sorted(run["sources"].items(), key=lambda item: item[1][0])]
        self.spool.write(canonical_bytes(dict(at=run["at"], seq=run["seq"], rows=run["rows"],
                                              payloads=payloads, sources=sources)))

    def _replay(self):
        """The spool as v0.1 coverage rows and descriptor stubs, in the order they were pushed."""
        with (self.work / "coverage.spool").open("rb") as handle:
            for line in handle:
                value = json.loads(line)
                if "d" in value:
                    yield dict(sequence=-1, captured_at=None, condition_id=self.names[value["d"]], kind="descriptor")
                    continue
                for offset, (cid, payload, source) in enumerate(value["rows"]):
                    digest, body = value["payloads"][payload]
                    yield dict(sequence=value["seq"] + offset, captured_at=value["at"], condition_id=self.names[cid],
                               kind="coverage", payload=body, payload_sha256=digest,
                               source_hashes=value["sources"][source])

    def finish(self, manifest: Mapping, groups: Mapping[str, str], *, check: Callable[[], None] = lambda: None) -> dict:
        """Write coverage under ``groups`` (condition -> group) and every stream, then ``bundle.json``.

        ``manifest`` carries every v0.2 manifest field except ``format``, ``coverage_groups`` and ``streams``.
        """
        self._end_run()
        self.spool.close()
        missing = sorted(self.covered - set(groups))
        if missing:
            raise BundleError("coverage_condition_without_group")
        coverage = self.streams["coverage"] = SortedStream(self.work, "coverage", self.spill_bytes)
        compactor, last = _Replay(groups), None
        for value in self._replay():
            check()
            for out in compactor.push(value):
                raw = canonical_bytes(out)
                key = (timestamp(out["captured_at"]), out["sequence"])
                if last is not None and key <= last:
                    raise BundleError("unsorted_coverage_stream")
                last = key
                coverage.add(key, raw)
        for out in compactor.finish():
            coverage.add((timestamp(out["captured_at"]), out["sequence"]), canonical_bytes(out))
        if not compactor.records:
            coverage.close()
            del self.streams["coverage"]
        refs, streams = [], {}
        for kind in sorted(self.streams):
            check()
            stream = self.streams[kind]
            if not self.compress:
                result = stream.finish(self.folder / f"{kind}.jsonl")
                refs.append(dict(path=f"{kind}.jsonl", sha256=result["sha256"], bytes=result["bytes"],
                                 records=result["records"]))
                streams[kind] = dict(result, spilled_runs=stream.spilled_runs)
                continue
            plain = self.work / f"{kind}.jsonl"
            decoded = stream.finish(plain)
            stored = gzip_stream.compress_file(plain, self.folder / f"{kind}.jsonl.gz", level=self.level,
                                               check=check)
            plain.unlink()
            refs.append(dict(path=f"{kind}.jsonl.gz", sha256=stored["sha256"], bytes=stored["bytes"],
                             decoded_sha256=decoded["sha256"], decoded_bytes=decoded["bytes"],
                             records=decoded["records"]))
            streams[kind] = dict(sha256=stored["sha256"], bytes=stored["bytes"], decoded_sha256=decoded["sha256"],
                                 decoded_bytes=decoded["bytes"], records=decoded["records"],
                                 sum256=decoded["sum256"], spilled_runs=stream.spilled_runs)
        members = {}
        for cid, gid in sorted(groups.items()):
            if cid in self.covered:
                members.setdefault(gid, []).append(cid)
        extra = dict(compression=gzip_stream.compression_record(self.level)) if self.compress else {}
        value = dict(manifest, **extra, format=self.format, streams=refs,
                     coverage_groups=[dict(group_id=g, condition_ids=c) for g, c in sorted(members.items())])
        raw = canonical_bytes(value)
        with (self.folder / "bundle.json").open("xb") as handle:
            handle.write(raw)
        shutil.rmtree(self.work)
        return dict(format=self.format, format_label=FORMAT_LABELS[self.format],
                    compression=gzip_stream.receipt_record(self.level) if self.compress else None,
                    manifest_bytes=len(raw), manifest_sha256=sha256(raw), streams=streams,
                    coverage_groups=len(members), v01=self.v01.result(),
                    v01_kinds={k: dict(bytes=self.kind_bytes[k], records=self.kind_records[k])
                               for k in sorted(self.kind_records)})

    def abort(self):
        """Close every handle so the caller can remove the partial folder."""
        self.run = None
        if not self.spool.closed:
            self.spool.close()
        for stream in self.streams.values():
            stream.close()


class _Replay(Compactor):
    """The W1 Compactor fed from the spool: descriptor stubs only mark first sight, coverage is compacted."""

    def __init__(self, groups):
        super().__init__(groups)
        self.records = 0

    def push(self, value):
        if value["kind"] == "descriptor":
            out = self.flush()
            self.seen.add(value["condition_id"])
            self.records += len(out)
            return out
        out = [v for v in super().push(value) if v["kind"] == "coverage"]
        self.records += len(out)
        return out

    def finish(self):
        out = super().finish()
        self.records += len(out)
        return out


def validate(folder: Path, expected: Mapping, *, limits: Limits | None = None,
             check: Callable[[], None] = lambda: None, visit: Callable[[object], None] | None = None) -> dict:
    """Stream the written bundle back: two-pass read, ``expand``, and the v0.1 row-set equality.

    ``expected`` is ``finish()``'s ``v01`` digest. ``visit`` sees every expanded v0.1 record once, in
    ``(captured_at, sequence)`` order. Returns per-kind counts of the expanded rows.
    """
    bundle = open_stream_bundle(folder, limits=limits)
    if bundle.format not in GROUPED_FORMATS:
        raise BundleError("unsupported_bundle_format")
    total, size, count, kinds, last = 0, 0, 0, Counter(), None
    for record in expand(bundle.records(), bundle.coverage_groups):
        if count % 10_000 == 0:
            check()
        key = (record.captured_at, record.sequence)
        if last is not None and key <= last:
            raise BundleError("unsorted_expanded_record")
        last = key
        raw = canonical_bytes(plain_row(record))
        total = (total + row_hash(raw)) % MOD
        size += len(raw)
        count += 1
        kinds[record.kind] += 1
        if visit is not None:
            visit(record)
    got = dict(bytes=size, records=count, sum256=f"{total:064x}")
    if got != {k: expected[k] for k in ("bytes", "records", "sum256")}:
        raise BundleError("v02_expansion_differs_from_v01_rows")
    return dict(expanded=got, kinds=dict(sorted(kinds.items())), input_bytes=bundle.input_bytes,
                coverage_groups=len(bundle.coverage_groups), conditions=len(bundle.conditions))


def file_digests(folder: Path, names: Iterable[str], chunk: int = 1024**2) -> dict:
    """Streaming SHA-256 and size of each named file."""
    out = {}
    for name in sorted(names):
        digest, size = hashlib.sha256(), 0
        with (folder / name).open("rb") as handle:
            while block := handle.read(chunk):
                digest.update(block)
                size += len(block)
        out[name] = dict(bytes=size, sha256=digest.hexdigest())
    return out

