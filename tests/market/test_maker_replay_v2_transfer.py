"""Maker replay v2 transfer manifest over bundles written by the REAL night exporters (U1 fix round 1).

The capture inputs are the market tests' fictional sealed 88a day (2030-01-10); the bundles, export.json
and receipts are produced by ``maker_replay_night_v02.export_day`` and the frozen v0.1
``maker_replay_night.export_day``, never hand-built. The panel day sets are monkeypatched to hold the
fictional day. Owner decision 19, A-defender M9, P-v2-defender NB4 and PB2(a)/(b).

Guards: the bundle transfer manifest contract (owner decision 19, registration draft §8): per-bundle
identity bound by hash before any parse (U1 Defender N1, r2 LOW-1), captured provenance (MF3), inputs
and records inside the day (PB2(a)/(b), r2 NOTE-2), and one shared RunBudget per verify (r2 C2).
"""
from __future__ import annotations

from copy import copy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json

import pytest

from maker_core.evidence.journal import canonical_bytes
from maker_core.replay import bundle_v02
from maker_core.replay.bundle import BundleError
from maker_core.replay.v2 import panel, transfer
from maker_core.replay.v2.limits import RunBudget, V2Limits
from weather.market import maker_replay_night as night_v01
from weather.market import maker_replay_night_v02 as night_v02
from tests.market.test_maker_replay_night import LATER, setup

DAY = LATER.date() - timedelta(days=1)


@pytest.fixture
def fictional_panel(monkeypatch):
    for name in ("QUOTE_DATES", "CALIBRATION_DATES"):
        monkeypatch.setattr(panel, name, (DAY,))
    monkeypatch.setattr(panel, "SETTLEMENT_ONLY_DATES", (DAY + timedelta(days=400),))
    monkeypatch.setattr(night_v02, "CALIBRATION_DATES", (DAY,))
    monkeypatch.setattr(night_v01, "CALIBRATION_DATES", (DAY,))


@pytest.fixture
def exports(tmp_path, fictional_panel):
    """Every export kind of one fictional day, each from the real exporter into its own output root."""
    args, _ = setup(tmp_path, multi=True)
    assert args.day == DAY.isoformat()
    roots = {}
    for kind, run in (("panel_night", lambda a: night_v02.export_day(a, "panel", now=LATER)),
                      ("calibration_night", lambda a: night_v02.export_day(a, "panel", now=LATER)),
                      ("calibration_hazard", lambda a: night_v02.export_day(a, "calibration", now=LATER)),
                      ("calibration_v01_reference", lambda a: night_v01.export_day(a, "calibration", now=LATER))):
        each = copy(args)
        each.out = tmp_path / "out" / kind
        each.out.parent.mkdir(exist_ok=True)
        assert run(each)["status"] == "SEALED"
        roots[kind] = each.out / each.day
    return roots


def build(pairs):
    return transfer.build(pairs, host_id="fictional-capture-host", created_at="2030-01-11T01:00:00+00:00")


def test_real_exports_build_and_verify_with_export_json_bound(exports):
    pairs = list(exports.items())
    doc = build(pairs)
    assert doc["format"] == "maker_core.replay.v2.transfer.v0.2"
    assert [(e["day"], e["export_kind"]) for e in doc["bundles"]] == [
        (DAY.isoformat(), k) for k in ("panel_night", "calibration_night", "calibration_hazard",
                                       "calibration_v01_reference")]
    by_kind = {e["export_kind"]: e for e in doc["bundles"]}
    for kind, root in exports.items():
        entry = by_kind[kind]
        assert entry["export_json_sha256"] == hashlib.sha256((root / "bundle" / "export.json").read_bytes()).hexdigest()
        assert set(entry["streams"]) == {p.name for p in (root / "bundle").iterdir()} - {"bundle.json", "export.json"}
    assert by_kind["calibration_v01_reference"]["bundle_format"] == "maker_core.replay.bundle.v0.1"
    assert by_kind["calibration_v01_reference"]["v01_equivalent_sha256"] == by_kind[
        "calibration_v01_reference"]["streams"]["events.jsonl"]["sha256"]
    assert by_kind["panel_night"]["bundle_format"] in transfer.V2_FORMATS
    verified = transfer.verify(doc, pairs)
    assert [v.export_kind for v in verified] == [k for k, _ in pairs]
    for item in verified:  # PB2(b): counts and bounds only, every record inside the day
        assert set(item.bounds) == {r.name for r in item.bundle.streams}
        for value in item.bounds.values():
            assert set(value) == {"records", "min_captured_at", "max_captured_at"}
            assert value["min_captured_at"].startswith(DAY.isoformat())
            assert value["max_captured_at"].startswith(DAY.isoformat())


def test_build_reads_no_stream_byte(exports, monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("a stream was read")
    monkeypatch.setattr(bundle_v02, "_hash_stream", refuse)
    monkeypatch.setattr(transfer, "open_stream_bundle", refuse)
    assert len(build(list(exports.items()))["bundles"]) == 4


def test_verify_compares_before_any_record_is_parsed(exports, monkeypatch):
    doc = build(list(exports.items()))
    monkeypatch.setattr(bundle_v02.StreamBundle, "records", lambda self: pytest.fail("records() called"))
    monkeypatch.setattr(transfer, "bounds", lambda bundle: pytest.fail("bounds scanned"))
    assert len(transfer.verify(doc, list(exports.items()), bounds_check=False)) == 4


def _first_stream(root):
    return sorted(p for p in (root / "bundle").iterdir() if p.name not in ("bundle.json", "export.json"))[0]


def test_one_changed_stream_byte_refuses_in_pass_one(exports):
    pairs = [("panel_night", exports["panel_night"])]
    doc = build(pairs)
    stream = _first_stream(exports["panel_night"])
    raw = bytearray(stream.read_bytes())
    # one byte, same size; bundle.json, export.json and the receipt untouched
    raw[raw.index(b'"sequence":') + 11 if stream.suffix == ".jsonl" else len(raw) // 2] ^= 1
    stream.write_bytes(bytes(raw))
    with pytest.raises(BundleError, match="stream_hash_or_size_mismatch|stream_decompression_failed"):
        transfer.verify(doc, pairs)


@pytest.mark.parametrize("name, field", [("bundle/export.json", "export_json_sha256"),
                                         ("receipt.json", "receipt_sha256")])
def test_export_json_and_receipt_are_bound_by_hash(exports, name, field):
    pairs = [("calibration_hazard", exports["calibration_hazard"])]
    doc = build(pairs)
    path = exports["calibration_hazard"] / name
    path.write_bytes(path.read_bytes().rstrip() + b" \n")
    with pytest.raises(BundleError, match=f"transfer_manifest_mismatch:{DAY}:{field}"):
        transfer.verify(doc, pairs)


def test_unlisted_duplicate_and_swapped_roots_are_refused(exports):
    doc = build([("calibration_hazard", exports["calibration_hazard"])])
    with pytest.raises(BundleError, match=f"transfer_manifest_unlisted:{DAY}:panel_night"):
        transfer.verify(doc, [("panel_night", exports["panel_night"])])
    with pytest.raises(BundleError, match="transfer_duplicate_bundle"):
        transfer.verify(doc, [("calibration_hazard", exports["calibration_hazard"])] * 2)
    with pytest.raises(BundleError, match=f"transfer_manifest_mismatch:{DAY}:"):
        transfer.verify(doc, [("calibration_hazard", exports["calibration_night"])])


def test_kind_day_format_and_receipt_disagreements_are_refused(exports, monkeypatch):
    with pytest.raises(BundleError, match="transfer_receipt_kind_mismatch"):
        build([("calibration_hazard", exports["calibration_night"])])
    with pytest.raises(BundleError, match="transfer_bundle_format_not_allowed"):
        build([("calibration_night", exports["calibration_v01_reference"])])
    with pytest.raises(BundleError, match="transfer_bundle_format_not_allowed"):
        build([("calibration_v01_reference", exports["calibration_hazard"])])
    with pytest.raises(BundleError, match="transfer_export_kind_unknown"):
        build([("calibration", exports["calibration_hazard"])])
    with pytest.raises(BundleError, match="transfer_duplicate_bundle"):
        build([("panel_night", exports["panel_night"])] * 2)
    monkeypatch.setattr(panel, "QUOTE_DATES", (DAY + timedelta(days=1),))
    with pytest.raises(BundleError, match="transfer_day_not_in_export_kind"):
        build([("panel_night", exports["panel_night"])])


def test_settlement_night_kind(exports, monkeypatch):
    monkeypatch.setattr(panel, "SETTLEMENT_ONLY_DATES", (DAY,))
    doc = build([("settlement_night", exports["panel_night"])])
    assert doc["bundles"][0]["export_kind"] == "settlement_night"


def _reseal(root, *, export_edit=None, stream_edit=None):
    """Forge a self-consistent root: rewrite export.json or one stream, then bundle.json and the receipt."""
    folder = root / "bundle"
    receipt = json.loads((root / "receipt.json").read_bytes())
    if export_edit is not None:
        export = json.loads((folder / "export.json").read_bytes())
        export_edit(export)
        (folder / "export.json").write_bytes(canonical_bytes(export))
    if stream_edit is not None:
        manifest = json.loads((folder / "bundle.json").read_bytes())
        stream = next(s for s in manifest["streams"] if s["path"] == stream_edit[0])
        raw = stream_edit[1]((folder / stream["path"]).read_bytes())
        (folder / stream["path"]).write_bytes(raw)
        stream.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
        (folder / "bundle.json").write_bytes(canonical_bytes(manifest))
    for path in folder.iterdir():
        raw = path.read_bytes()
        receipt["bundle"]["files"][path.name] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    (root / "receipt.json").write_bytes(canonical_bytes(receipt))


def test_a_bundle_relabelled_synthetic_is_refused(exports):
    """U1 Defender MF3: a captured bundle relabelled synthetic would run without declared intervals."""
    root = exports["calibration_hazard"]
    pairs = [("calibration_hazard", root)]
    doc = build(pairs)
    manifest = json.loads((root / "bundle" / "bundle.json").read_bytes())
    manifest["provenance"] = "synthetic"
    (root / "bundle" / "bundle.json").write_bytes(canonical_bytes(manifest))
    with pytest.raises(BundleError, match=f"transfer_manifest_mismatch:{DAY}:bundle_json_sha256"):
        transfer.verify(doc, pairs)
    _reseal(root)
    with pytest.raises(BundleError, match="transfer_bundle_not_captured"):
        build(pairs)


def test_pb2a_capture_input_outside_the_day_folder_is_refused(exports):
    root = exports["calibration_hazard"]
    other = f"maker_evidence/{DAY + timedelta(days=1)}/15-x/books.jsonl"
    _reseal(root, export_edit=lambda e: e["input_hashes"].update({other: "0" * 64}))
    with pytest.raises(BundleError, match=f"transfer_inputs_outside_day:{DAY}"):
        build([("calibration_hazard", root)])


def test_pb2a_cumulative_non_evidence_inputs_are_allowed(exports):
    root = exports["calibration_hazard"]
    _reseal(root, export_edit=lambda e: e["input_hashes"].update({"snapshots/x/settlements.jsonl": "0" * 64}))
    assert build([("calibration_hazard", root)])["bundles"]


@pytest.mark.parametrize("kind", ["panel_night", "calibration_v01_reference"])
def test_pb2b_record_outside_the_day_is_refused_by_the_bounds_scan(exports, kind):
    root = exports[kind]
    manifest = json.loads((root / "bundle" / "bundle.json").read_bytes())
    if manifest["format"] == "maker_core.replay.bundle.v0.3":
        pytest.skip("v0.3 streams are gzip; the forgery below rewrites plain lines")
    name = manifest["streams"][0]["path"]
    late = datetime.combine(DAY + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc).isoformat()

    def shift_last(raw):
        lines = raw.splitlines(keepends=True)
        value = json.loads(lines[-1])
        value["captured_at"] = late
        lines[-1] = canonical_bytes(value)
        return b"".join(lines)
    _reseal(root, stream_edit=(name, shift_last))
    doc = build([(kind, root)])
    assert transfer.verify(doc, [(kind, root)], bounds_check=False)  # pass one alone cannot see it
    with pytest.raises(BundleError, match=f"transfer_bounds_outside_day:{DAY}:{name}"):
        transfer.verify(doc, [(kind, root)])


def test_v03_decoded_digests_are_bound_when_the_exporter_writes_gzip(exports):
    root = exports["panel_night"]
    manifest = json.loads((root / "bundle" / "bundle.json").read_bytes())
    if manifest["format"] != "maker_core.replay.bundle.v0.3":
        pytest.skip("this tree's exporter writes v0.2; runs once X1's v0.3 writer is merged")
    doc = build([("panel_night", root)])
    entry = doc["bundles"][0]
    # the decoded hash and size are the identity; the stored (zlib-build-specific) ones are only recorded
    assert all(set(v) == {"decoded_sha256", "decoded_bytes", "records", "stored_sha256", "stored_bytes"}
               for v in entry["streams"].values())
    verified = transfer.verify(doc, [("panel_night", root)])
    assert verified[0].bounds and all(v["records"] for v in verified[0].bounds.values())
    receipt = json.loads((root / "receipt.json").read_bytes())
    kind = next(iter(receipt["bundle"]["kinds"]))
    receipt["bundle"]["kinds"][kind]["decoded_sha256"] = "0" * 64
    (root / "receipt.json").write_bytes(canonical_bytes(receipt))
    with pytest.raises(BundleError, match="transfer_receipt_bundle_mismatch"):
        build([("panel_night", root)])


@pytest.mark.parametrize("edit", [
    lambda d: d.update(extra=1),
    lambda d: d.update(format="maker_core.replay.v2.transfer.v0.1"),
    lambda d: d["bundles"].reverse(),
    lambda d: d["bundles"].append(dict(d["bundles"][0])),
    lambda d: d["bundles"][0].update(export_kind="calibration_v01_reference"),
    lambda d: d["bundles"][0].update(module_sha256="x"),
    lambda d: d["bundles"][0].pop("export_json_sha256"),
    lambda d: d["bundles"][0].update(format="v0.1"),
])
def test_malformed_committed_manifest_is_refused(exports, edit):
    pairs = [("calibration_night", exports["calibration_night"]), ("calibration_hazard", exports["calibration_hazard"])]
    doc = json.loads(json.dumps(build(pairs)))
    edit(doc)
    with pytest.raises(BundleError, match="transfer_manifest_invalid"):
        transfer.verify(doc, pairs)


def test_transfer_constants():
    assert transfer.TRANSFER_MANIFEST_PATH == "config/maker_replay_v2/transfer_manifest.json"
    assert transfer.EXPORT_KINDS[-1] == "calibration_v01_reference"
    assert transfer.days_of("calibration_v01_reference") == tuple(panel.CALIBRATION_DATES)
    assert date(2026, 9, 27) in transfer.days_of("calibration_hazard")


def test_verified_real_export_feeds_the_universe_producer_and_the_rule(exports):
    """Integration: real export_day -> build -> verify -> v0.2 universe rows -> §4 intervals (any v0.2/v0.3)."""
    from maker_core.replay.v2 import intervals, universe_v02
    from weather.market.maker_replay_universe_v02 import rows_of
    pairs = [("panel_night", exports["panel_night"])]
    verified = transfer.verify(build(pairs), pairs)
    bundle = verified[0].bundle
    rows = rows_of([bundle])
    assert {r["market_id"] for r in rows} == {"chicago", "nyc"}
    result = intervals.evaluate(universe_v02.day_inputs([bundle]), rows, panel="registered")
    assert {e["condition_id"] for e in result.exclusions} | {w["condition_id"] for w in result.windows} == {
        r["condition_id"] for r in rows}
    assert result.owner_exclusions[0]["matched_conditions"] == []


# ----------------------------------------------------------------------------- round 2: LOW-1, C2, NOTE-2
NESTED = b"[" * 200_000 + b"]" * 200_000  # under the 16 MiB export cap; json.loads raises RecursionError


@pytest.mark.parametrize("name, field", [("bundle/export.json", "export_json_sha256"),
                                         ("receipt.json", "receipt_sha256")])
def test_export_and_receipt_hashes_are_compared_before_any_parse(exports, monkeypatch, name, field):
    """U1 Defender r2 LOW-1: verify compares the raw export.json/receipt.json hash before parsing. A hostile
    deeply nested file is refused as a hash mismatch (a BundleError), never parsed and never a RecursionError."""
    pairs = [("calibration_hazard", exports["calibration_hazard"])]
    doc = build(pairs)
    (exports["calibration_hazard"] / name).write_bytes(NESTED)
    real = transfer._parse

    def parse(raw):
        assert raw != NESTED, "parsed before its hash was compared"
        return real(raw)
    monkeypatch.setattr(transfer, "_parse", parse)
    with pytest.raises(BundleError, match=f"^transfer_manifest_mismatch:{DAY}:{field}$"):
        transfer.verify(doc, pairs)


def test_verify_parses_exactly_the_bytes_it_hashed(exports, monkeypatch):
    """LOW-1: each of receipt.json, export.json and bundle.json is read from disk ONCE by verify, hashed, and
    only those same bytes are parsed (no second read between the hash compare and the parse)."""
    pairs = list(exports.items())
    doc = build(pairs)
    events, real_raw, real_parse = [], transfer._raw, transfer._parse

    def raw(path, cap):
        value, digest = real_raw(path, cap)
        events.append(("read", path.relative_to(path.parents[1] if path.parent.name == "bundle" else path.parent)
                       .as_posix(), str(path.parent), digest))
        return value, digest

    def parse(value):
        events.append(("parse", hashlib.sha256(value).hexdigest()))
        return real_parse(value)
    monkeypatch.setattr(transfer, "_raw", raw)
    monkeypatch.setattr(transfer, "_parse", parse)
    assert len(transfer.verify(doc, pairs, bounds_check=False)) == 4
    reads = [e for e in events if e[0] == "read"]
    assert len(reads) == len({(e[1], e[2]) for e in reads}) == 3 * len(pairs)
    hashed = set()
    for event in events:
        if event[0] == "read":
            hashed.add(event[3])
        else:
            assert event[1] in hashed, "parsed bytes that were never hashed"


def test_deeply_nested_json_refuses_as_a_bundle_error_in_build(exports):
    """``_parse`` maps RecursionError to the BundleError contract (build has no hash to compare against)."""
    root = exports["calibration_hazard"]
    (root / "bundle" / "export.json").write_bytes(NESTED)
    with pytest.raises(BundleError, match="^transfer_root_invalid$"):
        build([("calibration_hazard", root)])


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _recording_opens(monkeypatch, after=None):
    calls, real = [], transfer.open_stream_bundle

    def opener(path, **kwargs):
        calls.append(kwargs)
        bundle = real(path, **kwargs)
        if after is not None:
            after(len(calls))
        return bundle
    monkeypatch.setattr(transfer, "open_stream_bundle", opener)
    return calls


def test_verify_opens_every_bundle_on_one_shared_run_budget(exports, monkeypatch):
    """U1 Defender r2 C2: one ``RunBudget`` for the whole verify, shared by every bundle; ``V2Limits``."""
    pairs = list(exports.items())
    doc = build(pairs)
    calls = _recording_opens(monkeypatch)
    verified = transfer.verify(doc, pairs)
    assert len(calls) == 4 and len({id(c["run"]) for c in calls}) == 1
    assert isinstance(calls[0]["run"], RunBudget) and all(type(c["limits"]) is V2Limits for c in calls)
    assert calls[0]["run"].stored_bytes == sum(v.bundle.input_bytes for v in verified)
    mine = RunBudget()
    calls.clear()
    transfer.verify(doc, pairs, run=mine)
    assert {id(c["run"]) for c in calls} == {id(mine)}


def test_verify_is_bounded_by_the_shared_stored_total(exports):
    pairs = list(exports.items())
    doc = build(pairs)
    sizes = [v.bundle.input_bytes for v in transfer.verify(doc, pairs, bounds_check=False)]
    with pytest.raises(BundleError, match="^run_input_byte_cap$"):
        transfer.verify(doc, pairs, run=RunBudget(max_run_stored_bytes=sizes[0] + 1))


def test_the_bounds_scan_is_bounded_by_the_run_deadline(exports, monkeypatch):
    """Past the run deadline after the last open, the PB2(b) scan (transfer's own stream read) refuses
    ``run_time_cap``; before round 2 it ran unbounded by any run."""
    pairs = list(exports.items())
    doc = build(pairs)
    clock = FakeClock()

    def late(count):  # ``count`` accumulates over the verify calls below: the last open of each call
        if count % len(pairs) == 0:
            clock.now += 40_000.0
    _recording_opens(monkeypatch, after=late)
    assert transfer.verify(doc, pairs, bounds_check=False, clock=clock, run=RunBudget(clock=clock))
    clock.now = 0.0
    with pytest.raises(BundleError, match="^run_time_cap$"):
        transfer.verify(doc, pairs, clock=clock, run=RunBudget(clock=clock))
    clock.now = 0.0
    with pytest.raises(BundleError, match="^run_time_cap$"):  # the default run uses verify's clock
        transfer.verify(doc, pairs, clock=clock)


@pytest.mark.parametrize("key", [
    f"maker_evidence/{DAY}/../{DAY + timedelta(days=1)}/x.jsonl",
    f"./maker_evidence/{DAY + timedelta(days=1)}/x.jsonl",
    "maker_evidence\\" + str(DAY + timedelta(days=1)) + "\\x.jsonl",
    f"MAKER_EVIDENCE/{DAY + timedelta(days=1)}/x.jsonl",
    f"/maker_evidence/{DAY + timedelta(days=1)}/x.jsonl",
    f"maker_evidence//{DAY}/x.jsonl",
], ids=["dotdot", "dot-slash", "backslash", "case", "absolute", "empty-segment"])
def test_pb2a_non_normalised_input_keys_are_refused(exports, key):
    """U1 Defender r2 NOTE-2: PB2(a) is no longer a literal prefix test."""
    root = exports["calibration_hazard"]
    _reseal(root, export_edit=lambda e: e["input_hashes"].update({key: "0" * 64}))
    with pytest.raises(BundleError, match=f"^transfer_inputs_outside_day:{DAY}$"):
        build([("calibration_hazard", root)])


OTHER = DAY + timedelta(days=1)
OWN = f"maker_evidence/{DAY}/"


@pytest.mark.parametrize("key", [
    f"maker_evidence./{OTHER}/x.jsonl",  # Win32 strips the trailing dot: another day's real folder
    f"C:/maker_evidence/{OTHER}/x.jsonl",
    f"C:maker_evidence/{OTHER}/x.jsonl",
    f"maker_ev\u0131dence/{OTHER}/x.jsonl",  # dotless i survives casefold
    f"maker_evidence /{OTHER}/x.jsonl",
    f"release:maker_evidence/{OTHER}/x.jsonl",
    f"{OWN}x\x00/y",
    f"{OWN}x\ty",
    f"{OWN}CON",
    f"{OWN}nul.txt",
    f"{OWN}COM1",
    f"{OWN}x.jsonl:ads",
    f"{OWN}... ",
    f"{OWN}.. ",
    f"{OWN}a./b",
    f"{OWN}x?y",
    f"{OWN}\u00e9.jsonl",
    OWN + "x" * 600,
    "carry:2030-1-1",
    "carry:../x",
], ids=["trailing-dot", "drive-absolute", "drive-relative", "dotless-i", "trailing-space", "release-escape",
        "nul", "control", "device-con", "device-nul-ext", "device-com1", "ads", "dots-space", "dotdot-space",
        "dot-inside", "wildcard", "non-ascii", "too-long", "carry-malformed", "carry-path"])
def test_pb2a_windows_aliases_and_unsafe_keys_are_refused(exports, key):
    """U1r2 Defender NOTE-2: keys are ASCII printable, capped in length, with no drive, ADS, device name,
    Windows-invalid character or segment ending in a dot or space; ``:`` only in ``carry:<date>`` and the
    ``release:`` prefix, whose path obeys the same rule (including PB2(a)'s own-day evidence prefix)."""
    root = exports["calibration_hazard"]
    _reseal(root, export_edit=lambda e: e["input_hashes"].update({key: "0" * 64}))
    with pytest.raises(BundleError, match=f"^transfer_inputs_outside_day:{DAY}$"):
        build([("calibration_hazard", root)])


@pytest.mark.parametrize("key", [
    f"carry:{DAY - timedelta(days=1)}", "release:artifacts/maker/release.json",
    f"release:{OWN}15-x/books.jsonl", f"{OWN}15-x.y/books.jsonl.gz", "snapshots/x/settlements.jsonl",
])
def test_pb2a_keys_the_exporter_writes_are_admitted(exports, key):
    root = exports["calibration_hazard"]
    _reseal(root, export_edit=lambda e: e["input_hashes"].update({key: "0" * 64}))
    assert build([("calibration_hazard", root)])["bundles"]


def test_a_deeply_nested_stream_line_refuses_as_a_bounds_bundle_error(exports):
    """U1r2 Defender LOW-B: the bounds scan is the first parse of a plain line; a 200k-deep last line
    (400 KB, under the line cap) refuses ``transfer_bounds_outside_day`` instead of escaping as
    ``RecursionError``."""
    kind = "calibration_v01_reference"
    root = exports[kind]
    name = json.loads((root / "bundle" / "bundle.json").read_bytes())["streams"][0]["path"]

    def nest_last(raw):
        lines = raw.splitlines(keepends=True)
        lines[-1] = NESTED + b"\n"
        return b"".join(lines)
    _reseal(root, stream_edit=(name, nest_last))
    doc = build([(kind, root)])
    assert transfer.verify(doc, [(kind, root)], bounds_check=False)  # pass one does not parse the line
    with pytest.raises(BundleError, match=f"^transfer_bounds_outside_day:{DAY}:{name}$"):
        transfer.verify(doc, [(kind, root)])


def test_the_bounds_scan_uses_the_shared_run_not_each_bundle_lifetime(exports, monkeypatch):
    """U1r2 Defender NOTE-4 (mutant M1): a 2,000 s jump after the last open is under every bundle's own
    32,768 s lifetime and under the 4,096 s pass cap, but past a 1,000 s caller run, so only the shared run
    refuses the PB2(b) scan."""
    pairs = list(exports.items())
    doc = build(pairs)
    clock = FakeClock()

    def late(count):
        if count % len(pairs) == 0:
            clock.now += 2_000.0
    _recording_opens(monkeypatch, after=late)
    assert transfer.verify(doc, pairs, clock=clock, run=RunBudget(max_run_seconds=5_000, clock=clock))
    clock.now = 0.0
    with pytest.raises(BundleError, match="^run_time_cap$"):
        transfer.verify(doc, pairs, clock=clock, run=RunBudget(max_run_seconds=1_000, clock=clock))
