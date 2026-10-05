"""S1, S2 and S6 for maker replay v2 W0-W2 on fictional fixtures; one measurement per fresh process.

    python -m tools.research.maker_replay_v2.run s1 --out NEW_DIR [--trades N] [--union 170] [--book-depth 8]
    python -m tools.research.maker_replay_v2.run s6 --out NEW_DIR [--trades N] [--union 170]
    python -m tools.research.maker_replay_v2.run s2-input --out NEW_DIR [--trades N] [--union 170] [--book-depth 8]
    python -m tools.research.maker_replay_v2.run s2 --input CAPTURE_DIR --out NEW_DIR [--format v0.2|v0.1] [--tracemalloc]
    python -m tools.research.maker_replay_v2.run books --out NEW_DIR [--minutes 60] [--depths 4 8 16 32]

S1 writes one full fictional day in v0.1 and v0.2 form and reports bytes and records per kind. S6
writes the same day, reads both forms back through the two-pass stream reader, expands v0.2 to v0.1
and compares the canonical bytes with the elided v0.1 stream by SHA-256; it repeats that with
byte-identical view/descriptor repeats (so elision has work), and checks that a crafted coverage
mismatch is refused. S2 (W2) writes a fictional sealed 88a capture day (``s2-input``), then runs one
night export of it per process (``s2``: the v0.2 exporter, or the frozen v0.1 one as the baseline) and
reports the peak, the peak per exporter phase, the in-memory accumulators, and bytes and records per
kind. ``books`` measures book record bytes against levels a side. S3/S5/S7/S8/S9 (W3-W5) are
reached through this entry point too; their usage is in ``bench.py``. Output goes only under
``--out``. Engineering plan:
docs/research/maker-replay-v2-engineering-plan-DRAFT.md. Heavy work: run it through
``scripts/ops/workstation_heavy.ps1`` (``weather_heavy``), serially.
"""
from __future__ import annotations

import argparse
import hashlib
from collections import Counter
from datetime import date
import json
from pathlib import Path
import time

from maker_core.evidence.journal import canonical_bytes
from maker_core.replay.bundle import (FORMAT, HOST_MAX_BYTES, HOST_MAX_RECORDS, HOST_MAX_SECONDS, BundleError,
                                      Limits, sha256)
from maker_core.replay.bundle_v02 import FORMAT_V02, open_stream_bundle
from maker_core.replay.v2.compaction import Compactor, elide, expand, stream_digest
from tools.research.maker_replay_v2 import bench
from tools.research.maker_replay_v2.fixture170 import Day

DAY = date(2026, 9, 27)  # a fictional day; nothing captured is read
LIMITS = dict(max_bytes=HOST_MAX_BYTES, max_records=HOST_MAX_RECORDS, max_seconds=HOST_MAX_SECONDS)


class _Stream:
    def __init__(self, path):
        self.path, self.handle = path, path.open("xb")
        self.sha, self.bytes, self.records = hashlib.sha256(), 0, 0

    def write(self, raw):
        self.handle.write(raw)
        self.sha.update(raw)
        self.bytes += len(raw)
        self.records += 1

    def close(self):
        self.handle.close()
        return dict(path=self.path.name, sha256=self.sha.hexdigest(), bytes=self.bytes, records=self.records)


def write_forms(day: Day, out: Path) -> dict:
    """One streaming pass: v0.1 as one sorted ``events.jsonl``, v0.2 as one sorted stream per kind."""
    v01, v02 = out / "v0.1", out / "v0.2"
    v01.mkdir(parents=True)
    v02.mkdir()
    events, streams = _Stream(v01 / "events.jsonl"), {}
    sizes = {"v0.1": Counter(), "v0.2": Counter()}
    counts = {"v0.1": Counter(), "v0.2": Counter()}
    compactor = Compactor(day.groups)

    def emit(values):
        for value in values:
            raw = canonical_bytes(value)
            kind = value["kind"]
            if kind not in streams:
                streams[kind] = _Stream(v02 / f"{kind}.jsonl")
            streams[kind].write(raw)
            sizes["v0.2"][kind] += len(raw)
            counts["v0.2"][kind] += 1

    try:
        for value in day.rows():
            raw = canonical_bytes(value)
            events.write(raw)
            sizes["v0.1"][value["kind"]] += len(raw)
            counts["v0.1"][value["kind"]] += 1
            emit(compactor.push(value))
        emit(compactor.finish())
    finally:
        refs = [events.close()] + [streams[k].close() for k in sorted(streams)]
    common = dict(day=day.day.isoformat(), sealed_at=day.end.isoformat(), provenance="synthetic",
                  conditions=day.conditions())
    for folder, manifest in ((v01, dict(common, format=FORMAT, streams=refs[:1])),
                             (v02, dict(common, format=FORMAT_V02, coverage_groups=day.coverage_groups(),
                                        streams=refs[1:]))):
        (folder / "bundle.json").write_bytes(canonical_bytes(manifest))
    return dict(v01=v01, v02=v02, sizes=sizes, counts=counts)


def _peak_rss():
    try:
        import psutil
        info = psutil.Process().memory_info()
        return getattr(info, "peak_wset", None) or info.rss
    except ImportError:
        return None


def _forms_table(written):
    kinds = sorted(set(written["counts"]["v0.1"]) | set(written["counts"]["v0.2"]))
    rows = {}
    for kind in kinds:
        b1, b2 = written["sizes"]["v0.1"][kind], written["sizes"]["v0.2"][kind]
        rows[kind] = dict(v01_bytes=b1, v02_bytes=b2, v01_records=written["counts"]["v0.1"][kind],
                          v02_records=written["counts"]["v0.2"][kind],
                          bytes_reduction=round(1 - b2 / b1, 6) if b1 else None)
    total = {f: sum(r[f] for r in rows.values()) for f in ("v01_bytes", "v02_bytes", "v01_records", "v02_records")}
    total["bytes_reduction"] = round(1 - total["v02_bytes"] / total["v01_bytes"], 6)
    manifests = {form: (written[form.replace(".", "")] / "bundle.json").stat().st_size for form in ("v0.1", "v0.2")}
    return dict(per_kind=rows, total=total, manifest_bytes=manifests,
                v02_bundle_bytes=total["v02_bytes"] + manifests["v0.2"], gib=1024**3)


def s1(args):
    day = Day(DAY, union=args.union, trades=args.trades, book_depth=args.book_depth)
    started = time.perf_counter()
    written = write_forms(day, args.out)
    elapsed = time.perf_counter() - started
    table = _forms_table(written)
    return dict(measurement="S1", status="MEASURED", fixture=day.stats(), trades=args.trades,
                book_depth=args.book_depth, seconds=round(elapsed, 1),
                peak_rss_bytes=_peak_rss(), v02_within_1_gib=table["v02_bundle_bytes"] <= 1024**3, **table)


def _equivalence(day, out):
    written = write_forms(day, out)
    limits = Limits(**LIMITS)
    started = time.perf_counter()
    b2 = open_stream_bundle(written["v02"], limits=limits)
    rolls, horizons, expanded = Counter(), {}, []

    def watch(records):
        for record in records:
            if record.kind == "descriptor":
                h = record.payload["horizon_days"]
                if record.condition_id in horizons and horizons[record.condition_id] != h:
                    rolls[f"{horizons[record.condition_id]}->{h}"] += 1
                horizons[record.condition_id] = h
            yield record

    got = stream_digest(watch(expand(b2.records(), b2.coverage_groups)))
    b1 = open_stream_bundle(written["v01"], limits=limits)
    want = stream_digest(elide(b1.records()))
    full = sum(written["counts"]["v0.1"].values())
    return dict(byte_identical=got == want, expanded=got, v01_elided=want, v01_records=full,
                elided_duplicates=full - want["records"], horizon_rolls=dict(sorted(rolls.items())),
                coverage_groups=len(b2.coverage_groups), v02_bytes=b2.input_bytes, v01_bytes=b1.input_bytes,
                read_and_compare_seconds=round(time.perf_counter() - started, 1))


def s6(args):
    started = time.perf_counter()
    result = dict(measurement="S6", status="MEASURED", trades=args.trades)
    day = Day(DAY, union=args.union, trades=args.trades)
    result["fixture"] = day.stats()
    result["exporter_faithful"] = _equivalence(day, args.out / "faithful")
    result["with_repeats"] = _equivalence(Day(DAY, union=args.union, trades=args.trades, repeat_views=True),
                                          args.out / "repeats")
    try:
        write_forms(Day(DAY, union=args.union, trades=args.trades, mismatch_minute=600), args.out / "mismatch")
        result["group_refusal"] = dict(fired=False)
    except BundleError as exc:
        result["group_refusal"] = dict(fired=str(exc) == "coverage_group_mismatch", error=str(exc))
    result["seconds"] = round(time.perf_counter() - started, 1)
    result["peak_rss_bytes"] = _peak_rss()
    result["pass"] = (result["exporter_faithful"]["byte_identical"] and result["with_repeats"]["byte_identical"]
                      and result["with_repeats"]["elided_duplicates"] > 0 and result["group_refusal"]["fired"]
                      and bool(result["exporter_faithful"]["horizon_rolls"]))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("measurement", choices=("s1", "s6", "s2-input", "s2", "books", *bench.MEASUREMENTS))
    parser.add_argument("--out", type=Path, required=True, help="new directory for the fictional bundles")
    parser.add_argument("--trades", type=int, default=2000)
    parser.add_argument("--union", type=int, default=170)
    parser.add_argument("--book-depth", type=int, default=8, help="S1 and s2-input: price levels per book side")
    parser.add_argument("--input", type=Path, help="s2: the capture folder an s2-input run wrote")
    parser.add_argument("--format", choices=("v0.2", "v0.1"), default="v0.2", help="s2: the exporter measured")
    parser.add_argument("--tracemalloc", action="store_true", help="s2: attribute Python allocations (slower)")
    parser.add_argument("--max-output-bytes", type=int, default=HOST_MAX_BYTES, help="s2: the export output cap")
    parser.add_argument("--depths", type=int, nargs="+", default=[4, 8, 16, 32], help="books: levels a side")
    # S3/S5/S7/S8/S9 (W3-W5): tools/research/maker_replay_v2/bench.py. It owns --minutes (default None, filled
    # per measurement by bench.DEFAULTS); s2-input and books fill their own default below.
    bench.add_arguments(parser)
    args = parser.parse_args(argv)
    if args.measurement == "s2" and args.input is None:
        parser.error("s2 needs --input")
    if args.out.exists():
        parser.error("--out must be a new directory")
    args.out.mkdir(parents=True)
    if args.measurement in bench.MEASUREMENTS:
        result = bench.run(args.measurement, args)
    elif args.measurement in ("s1", "s6"):
        result = (s1 if args.measurement == "s1" else s6)(args)
    else:
        from tools.research.maker_replay_v2 import s2
        minutes = 1440 if args.minutes is None else args.minutes  # s2-input and books: minutes captured
        if args.measurement == "s2-input":
            result = s2.s2_input(args.out, DAY, union=args.union, trades=args.trades, book_depth=args.book_depth,
                                 minutes=minutes)
        elif args.measurement == "s2":
            result = s2.s2(DAY, args.input, args.out, form=args.format, trace=args.tracemalloc,
                           max_output_bytes=args.max_output_bytes)
        else:
            result = s2.books(DAY, args.out, depths=args.depths, minutes=minutes, union=args.union,
                              trades=args.trades)
    raw = json.dumps(result, sort_keys=True, default=str, indent=1)
    (args.out / f"{args.measurement}.json").write_text(raw + "\n", encoding="utf-8")
    print(raw)
    print("sha256(result)", sha256(raw.encode()))
    return 0 if result.get("pass", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
