from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path

import pytest

from maker_core.evidence.journal import canonical_bytes, digest
from maker_core.quoting.policy import decide
from maker_core.replay.__main__ import main
from maker_core.replay.bundle import (BundleError, HOST_MAX_BYTES, HOST_MAX_RECORDS, HOST_MAX_SECONDS, Limits,
                                      load_bundle, sha256)
from maker_core.replay.diagnostics import coverage_report, report_bytes, write_report
from maker_core.replay.timeline import Timeline
from .fixtures.replay_bundle import seal, write_day, write_three_days


def save_manifest(root, manifest):
    (root / "bundle.json").write_bytes(canonical_bytes(manifest))


def test_three_day_two_market_coverage_excludes_gap(tmp_path):
    days = [load_bundle(path) for path in write_three_days(tmp_path)]
    assert len({bundle.day for bundle in days}) == 3
    assert {condition.market_id for bundle in days for condition in bundle.conditions} == {
        "fictional-a", "fictional-b"}
    for bundle in days:
        report = coverage_report(bundle, "blind_re1")
        first, second = report["coverage"]
        assert (first["book_capture_minutes"], first["excluded_minutes"]) == (3, 1)
        assert (second["book_capture_minutes"], second["excluded_minutes"]) == (4, 0)
        assert first["exclusions"][0]["reason"] == "MISSING_BOOK_CAPTURE"
        assert first["evaluable_minutes"] is None
        assert report["policy_executed"] is False
        assert "scores" not in report
        assert [r.captured_at for r in bundle.records] == sorted(r.captured_at for r in bundle.records)


def test_capture_cutoff_and_payload_are_immutable(tmp_path):
    root = tmp_path / "day"
    write_day(root)
    bundle = load_bundle(root)
    timeline = Timeline(bundle)
    condition = bundle.conditions[0]
    before = timeline.at(condition.active_from)
    assert before.latest("plugin_input", condition.condition_id) is None
    now = condition.active_from + timedelta(seconds=125)
    snapshot = timeline.at(now)
    row = snapshot.latest("plugin_input", condition.condition_id)
    assert row.payload["p_yes"] == .5
    assert snapshot.latest("settlement", condition.condition_id) is None
    assert all(record.captured_at <= now for record in snapshot.records)
    assert timeline.at(condition.active_from + timedelta(seconds=181)).latest(
        "plugin_input", condition.condition_id).payload["p_yes"] == .8
    with pytest.raises(TypeError):
        row.payload["p_yes"] = .9
    with pytest.raises(TypeError):
        bundle.input_hashes["bundle.json"] = "f" * 64


def test_future_input_cannot_change_earlier_decision(tmp_path, inputs):
    root = tmp_path / "day"
    manifest, records = write_day(root)

    def decision():
        bundle = load_bundle(root)
        condition = bundle.conditions[0]
        snapshot = Timeline(bundle).at(condition.active_from + timedelta(seconds=125))
        record = snapshot.latest("plugin_input", condition.condition_id)
        # Minimal fictional provider consumes only its admitted captured record.
        value = replace(inputs.fair_value, p_yes=record.payload["p_yes"], joint=None,
                        inputs_hash=digest(record.payload))
        return canonical_bytes(decide(replace(inputs, fair_value=value)))

    original = decision()
    for record in records:
        if record["kind"] == "plugin_input" and record["payload"]["p_yes"] == .8:
            record["payload"]["p_yes"] = .99
            record["payload_sha256"] = sha256(canonical_bytes(record["payload"]))
    seal(root, manifest, records)
    assert decision() == original


def test_report_bytes_repeat_across_locations_and_create_only(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    write_day(first)
    write_day(second)
    report = coverage_report(load_bundle(first), "no_quote")
    assert report_bytes(report) == report_bytes(coverage_report(load_bundle(second), "no_quote"))
    out = tmp_path / "out"
    write_report(out, report, input_directory=first)
    original = (out / "report.json").read_bytes()
    with pytest.raises(FileExistsError):
        write_report(out, report, input_directory=first)
    assert (out / "report.json").read_bytes() == original
    with pytest.raises(BundleError, match="overlap"):
        write_report(first / "out", report, input_directory=first)
    with pytest.raises(BundleError, match="report_byte_cap"):
        write_report(tmp_path / "small", report, input_directory=first, max_bytes=1)
    assert not (tmp_path / "small").exists()


@pytest.mark.parametrize("flags", [
    ["--compare"], ["--compare", "--pre-registration-sha256", "a" * 64],
    ["--pre-registration", "owner.json"], ["--pre-registration-sha256", "a" * 64],
])
def test_comparison_refuses_before_any_reads(tmp_path, monkeypatch, flags):
    def forbidden(*args, **kwargs):
        pytest.fail("comparison gate must precede bundle and registration reads")
    monkeypatch.setattr(Path, "open", forbidden)
    with pytest.raises(SystemExit) as exc:
        main(["run", "--bundle", str(tmp_path / "missing"), "--out", str(tmp_path / "out"), *flags])
    assert exc.value.code == 2


@pytest.mark.parametrize("provenance", ["synthetic", "captured"])
def test_cli_defaults_diagnostic_only_even_when_policy_requested(tmp_path, provenance):
    root, out = tmp_path / "day", tmp_path / "out"
    manifest, _ = write_day(root)
    manifest["provenance"] = provenance  # This is a fixture label, not real data.
    save_manifest(root, manifest)
    assert main(["run", "--bundle", str(root), "--out", str(out), "--policy", "informed-v0"]) == 0
    report = json.loads((out / "report.json").read_bytes())
    assert report["mode"] == "diagnostic-only"
    assert report["policy_executed"] is False
    assert report["parity"]["status"] == "NOT_RUN"
    assert not {"scores", "comparisons", "pnl", "fills"}.intersection(report)


@pytest.mark.parametrize("change,reason", [
    (lambda m: m.update(sealed_at="2020-01-01T23:59:00Z"), "not_closed"),
    (lambda m: m.update(day="20200101"), "noncanonical_day"),
    (lambda m: m.update(unexpected=True), "unexpected_fields"),
    (lambda m: m["streams"][0].update(path="../records.jsonl"), "stream_path"),
    (lambda m: m["streams"][0].update(path="records.jsonl:stream"), "stream_path"),
    (lambda m: m["streams"][0].update(sha256="0" * 64), "hash_or_size"),
    (lambda m: m["streams"][0].update(records=0), "record_count"),
    (lambda m: m["streams"].append(dict(m["streams"][0])), "stream_path"),
    (lambda m: m["conditions"].append(dict(m["conditions"][0])), "duplicate_condition"),
    (lambda m: m["conditions"][0].update(active_from="2020-01-01T00:00:01Z"), "active_window"),
])
def test_manifest_corruption_refuses(tmp_path, change, reason):
    root = tmp_path / "day"
    manifest, _ = write_day(root)
    change(manifest)
    save_manifest(root, manifest)
    with pytest.raises(BundleError, match=reason):
        load_bundle(root)


@pytest.mark.parametrize("change,reason", [
    (lambda rows: rows[0].update(sequence=True), "integer"),
    (lambda rows: rows[0].update(sequence=rows[1]["sequence"]), "duplicate_sequence"),
    (lambda rows: rows[0].update(captured_at="2020-01-02T00:00:00Z"), "outside_day"),
    (lambda rows: rows[0].update(captured_at="2020-01-01T00:00:00"), "utc_text"),
    (lambda rows: rows[0].update(condition_id="unlisted"), "unknown_condition"),
    (lambda rows: rows[0].update(kind=[]), "identity"),
    (lambda rows: rows[0].update(payload_sha256="0" * 64), "payload_hash"),
    (lambda rows: rows[0].update(source_hashes={}), "source_hashes"),
])
def test_record_corruption_refuses_even_with_resealed_stream(tmp_path, change, reason):
    root = tmp_path / "day"
    manifest, records = write_day(root)
    change(records)
    seal(root, manifest, records)
    with pytest.raises(BundleError, match=reason):
        load_bundle(root)


def test_caps_are_enforced_and_cannot_exceed_the_host(tmp_path):
    root = tmp_path / "day"
    write_day(root)
    with pytest.raises(BundleError, match="input_byte_cap"):
        load_bundle(root, limits=Limits(max_bytes=10))
    with pytest.raises(BundleError, match="integer|count_cap"):
        load_bundle(root, limits=Limits(max_records=1))
    ticks = iter([0, 1])
    with pytest.raises(BundleError, match="time_cap"):
        load_bundle(root, limits=Limits(max_seconds=.5), clock=lambda: next(ticks))
    # Explicit ceilings may exceed the diagnostic defaults only up to the 16 GB host caps.
    Limits(max_bytes=2**30, max_records=1_000_000, max_seconds=2700)
    for limits in ({"max_bytes": HOST_MAX_BYTES + 1}, {"max_records": HOST_MAX_RECORDS + 1},
                   {"max_seconds": HOST_MAX_SECONDS + 1}, {"max_seconds": float("nan")},
                   {"max_seconds": float("inf")}):
        with pytest.raises(BundleError):
            Limits(**limits)


@pytest.mark.parametrize("raw", [b'{"format":1,"format":2}', b'{"n":NaN}', b'{"n":1e999}'])
def test_ambiguous_json_refuses(tmp_path, raw):
    root = tmp_path / "day"
    root.mkdir()
    (root / "bundle.json").write_bytes(raw)
    with pytest.raises(BundleError, match="invalid_json"):
        load_bundle(root)


def test_redirected_input_refuses(tmp_path):
    real = tmp_path / "real"
    write_day(real)
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("host does not grant symlink creation")
    with pytest.raises(BundleError, match="redirected_path"):
        load_bundle(link)
