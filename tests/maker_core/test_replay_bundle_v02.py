"""W1: bundle v0.2 stream reader, coverage groups and the exact v0.2 -> v0.1 expansion (fictional only)."""
from datetime import date
import json

import pytest

from maker_core.evidence.journal import canonical_bytes
from maker_core.replay.bundle import Bundle, BundleError, Limits, load_bundle, sha256
from maker_core.replay.bundle_v02 import StreamBundle, load_any, open_stream_bundle
from maker_core.replay.v2.compaction import Compactor, compact, elide, expand, row, stream_digest
from tools.research.maker_replay_v2.fixture170 import Day
from tools.research.maker_replay_v2.run import write_forms

LIMITS = Limits(2**30, 10**6, 300)


def _day(**kwargs):
    # 03:50-04:10 UTC crosses New York and Toronto local midnight (the horizon roll).
    return Day(date(2026, 9, 27), union=60, trades=300, start_minute=230, minutes=20, **kwargs)


@pytest.fixture
def forms(tmp_path):
    return write_forms(_day(), tmp_path / "forms")


def _equivalent(written):
    v02 = open_stream_bundle(written["v02"], limits=LIMITS)
    v01 = open_stream_bundle(written["v01"], limits=LIMITS)
    return stream_digest(expand(v02.records(), v02.coverage_groups)), stream_digest(elide(v01.records()))


def test_expansion_is_byte_identical_across_the_horizon_roll(forms):
    got, want = _equivalent(forms)
    assert got == want
    assert want["records"] == sum(forms["counts"]["v0.1"].values())  # exporter-faithful: nothing to elide
    assert forms["counts"]["v0.2"]["coverage"] * 5 < forms["counts"]["v0.1"]["coverage"]
    rolls = {r.payload["horizon_days"] for r in open_stream_bundle(forms["v02"], limits=LIMITS).records()
             if r.kind == "descriptor"}
    assert rolls == {0, 1, 2}


def test_elided_duplicates_lose_only_their_own_rows(tmp_path):
    written = write_forms(_day(repeat_views=True), tmp_path)
    got, want = _equivalent(written)
    assert got == want
    elided = sum(written["counts"]["v0.1"].values()) - want["records"]
    assert elided > 0 and elided == (sum(written["counts"]["v0.1"].values()) - sum(written["counts"]["v0.2"].values())
                                     - written["counts"]["v0.1"]["coverage"] + written["counts"]["v0.2"]["coverage"])


def test_stream_reader_matches_the_frozen_v01_reader(forms):
    frozen = load_bundle(forms["v01"], limits=LIMITS)
    streamed = open_stream_bundle(forms["v01"], limits=LIMITS)
    assert stream_digest(frozen.records) == stream_digest(streamed.records())
    assert frozen.input_hashes == streamed.input_hashes and frozen.conditions == streamed.conditions
    assert isinstance(load_any(forms["v01"], limits=LIMITS), Bundle)
    assert isinstance(load_any(forms["v02"], limits=LIMITS), StreamBundle)


def test_group_refusal_fires_on_a_crafted_mismatch(tmp_path):
    with pytest.raises(BundleError, match="^coverage_group_mismatch$"):
        write_forms(_day(mismatch_minute=240), tmp_path)


def test_compactor_refuses_ungrouped_or_reordered_coverage():
    rows = list(_day().rows())
    day = _day()
    with pytest.raises(BundleError, match="coverage_condition_without_group"):
        list(compact(rows, {}))
    groups = dict(day.groups)
    moved = sorted(c for c, g in groups.items() if g == "sub0-0")[0]
    groups[moved] = "sub1-0"  # a member of another socket's subscription disagrees with this group's state
    with pytest.raises(BundleError, match="coverage_group_mismatch"):
        list(compact(rows, groups))
    with pytest.raises(BundleError, match="unsorted_compaction_input"):
        compactor = Compactor(day.groups)
        compactor.push(rows[1])
        compactor.push(rows[0])


# -- tampered v0.2 bundles: each refusal fires before or during streaming, never silently ----------------

def _rewrite(folder, name, lines, manifest_edit=None):
    raw = b"".join(lines)
    (folder / name).write_bytes(raw)
    manifest = json.loads((folder / "bundle.json").read_bytes())
    for stream in manifest["streams"]:
        if stream["path"] == name:
            stream.update(sha256=sha256(raw), bytes=len(raw), records=len(lines))
    if manifest_edit:
        manifest_edit(manifest)
    (folder / "bundle.json").write_bytes(canonical_bytes(manifest))


def _lines(folder, name):
    return (folder / name).read_bytes().splitlines(keepends=True)


def test_unsorted_stream_is_refused(forms):
    lines = _lines(forms["v02"], "book.jsonl")
    lines[3], lines[4] = lines[4], lines[3]
    _rewrite(forms["v02"], "book.jsonl", lines)
    with pytest.raises(BundleError, match="unsorted_stream"):
        list(open_stream_bundle(forms["v02"], limits=LIMITS).records())


def test_pass_one_refuses_changed_bytes_before_any_record(forms):
    path = forms["v02"] / "trade.jsonl"
    raw = bytearray(path.read_bytes())
    raw[10] ^= 1
    path.write_bytes(bytes(raw))
    with pytest.raises(BundleError, match="stream_hash_or_size_mismatch"):
        open_stream_bundle(forms["v02"], limits=LIMITS)


def test_stream_changed_between_passes_is_refused(forms):
    bundle = open_stream_bundle(forms["v02"], limits=LIMITS)
    path = forms["v02"] / "coverage.jsonl"
    raw = path.read_bytes()
    path.write_bytes(raw.replace(b'"trade_stream_ok":true', b'"trade_stream_ok":fals', 1)[:len(raw)])
    with pytest.raises(BundleError, match="^input_changed_between_passes$"):
        list(bundle.records())


def test_duplicate_sequence_across_streams_is_refused(forms):
    book = json.loads(_lines(forms["v02"], "book.jsonl")[0])
    trade_lines = _lines(forms["v02"], "trade.jsonl")
    trade = json.loads(trade_lines[0])
    trade["sequence"] = book["sequence"]
    _rewrite(forms["v02"], "trade.jsonl", [canonical_bytes(trade)] + trade_lines[1:])
    with pytest.raises(BundleError, match="duplicate_sequence|unsorted"):
        list(open_stream_bundle(forms["v02"], limits=LIMITS).records())


@pytest.mark.parametrize("edit, error", [
    (lambda m: m["coverage_groups"][0]["condition_ids"].append("0xnot-a-condition"), "unknown_or_shared"),
    (lambda m: m["coverage_groups"][1]["condition_ids"].insert(0, m["coverage_groups"][0]["condition_ids"][0]),
     "unknown_or_shared|noncanonical"),
    (lambda m: m["coverage_groups"][0]["condition_ids"].reverse(), "noncanonical_coverage_group_order"),
    (lambda m: m["coverage_groups"].append(dict(m["coverage_groups"][0])), "duplicate_or_empty"),
    (lambda m: m.pop("coverage_groups"), "unexpected_fields"),
])
def test_coverage_group_manifest_refusals(forms, edit, error):
    lines = _lines(forms["v02"], "trade.jsonl")
    _rewrite(forms["v02"], "trade.jsonl", lines, edit)
    with pytest.raises(BundleError, match=error):
        open_stream_bundle(forms["v02"], limits=LIMITS)


def test_v02_coverage_must_name_a_known_group(forms):
    lines = _lines(forms["v02"], "coverage.jsonl")
    value = json.loads(lines[0])
    _rewrite(forms["v02"], "coverage.jsonl", [canonical_bytes(dict(value, group_id="sub-unknown"))] + lines[1:])
    with pytest.raises(BundleError, match="unknown_coverage_group"):
        list(open_stream_bundle(forms["v02"], limits=LIMITS).records())
    value.pop("group_id")
    _rewrite(forms["v02"], "coverage.jsonl", [canonical_bytes(dict(value, condition_id="x"))] + lines[1:])
    with pytest.raises(BundleError, match="unexpected_fields"):
        list(open_stream_bundle(forms["v02"], limits=LIMITS).records())


def test_expansion_refuses_a_group_sequence_that_does_not_fit_the_run(forms):
    bundle = open_stream_bundle(forms["v02"], limits=LIMITS)
    records = list(bundle.records())
    runs = {}
    for index, record in enumerate(records):
        if record.kind == "coverage":
            runs.setdefault(record.captured_at, []).append(index)
    index = next(ix[1] for ix in runs.values() if len(ix) > 1)
    shifted = records[index].__class__(**{**records[index].__dict__, "sequence": records[index].sequence + 10**9})
    records[index] = shifted
    with pytest.raises(BundleError, match="coverage_group_sequence_mismatch"):
        list(expand(records, bundle.coverage_groups))


def test_row_round_trips_reader_records(forms):
    bundle = open_stream_bundle(forms["v02"], limits=LIMITS)
    first = next(r for r in bundle.records() if r.kind == "coverage")
    assert set(row(first)) == {"sequence", "captured_at", "group_id", "kind", "payload", "payload_sha256",
                               "source_hashes"}
