from datetime import timedelta
import json
import socket

import pytest
from maker_core.replay.bundle import load_bundle
from maker_core.replay.payloads import decode
from weather.market.maker_evidence_store import EvidenceStore, encoded
from weather.market.maker_replay_bundle import export, main, ExportReader
from tests.market.test_maker_plugin_dry_run import layout, NOW


def args_for(tmp_path, **kwargs):
    args, folder, segment = layout(tmp_path, **kwargs)
    args.out = tmp_path/"bundle"
    args.max_output_bytes = 64*1024**2
    args.max_records = 100000
    return args, folder, segment


def test_sealed_export_roundtrip_is_deterministic_and_read_only(tmp_path, monkeypatch):
    args, _, _ = args_for(tmp_path, minutes=2, compressed=True)
    before = {p: p.read_bytes() for p in args.data_root.rglob("*") if p.is_file()}
    monkeypatch.setattr(socket, "socket", lambda *a, **k: pytest.fail("network accessed"))
    summary = export(args, now=NOW+timedelta(days=1))
    bundle = load_bundle(args.out)
    assert len(bundle.conditions) == 3
    assert summary["counts"]["book"] == 6
    assert summary["counts"]["plugin_input"] > 0
    for row in bundle.records:
        decode(row)  # Native weather payloads must actually satisfy core semantics.
    coverage = [decode(r) for r in bundle.records if r.kind == "coverage"]
    assert coverage and not any(r.trade_stream_ok for r in coverage)
    first = {p.name: p.read_bytes() for p in args.out.iterdir()}
    args.out = tmp_path/"repeat"
    export(args, now=NOW+timedelta(days=5))
    assert first == {p.name: p.read_bytes() for p in args.out.iterdir()}
    assert before == {p: p.read_bytes() for p in args.data_root.rglob("*") if p.is_file()}


def test_trade_lifecycle_mapping_clocks_and_freshness(tmp_path):
    args, _, _ = args_for(tmp_path)
    when = NOW + timedelta(seconds=5)
    store = EvidenceStore(args.data_root/"maker_evidence", clock=lambda: when)
    store.event("stream_lifecycle", dict(state="connected", channel="trades",
                subscription=store.subscription(["100", "101"], "trades")))
    when = NOW+timedelta(seconds=10)
    store.record("trades", encoded(dict(event_type="last_trade_price", asset_id="101",
                  market="0x"+f"{1:064x}", timestamp=str(int(when.timestamp()*1000)),
                  price=".47", size="10", side="SELL")))
    when = NOW+timedelta(seconds=15)
    store.event("stream_lifecycle", dict(state="disconnected", channel="trades",
                subscription=store.subscription(["100", "101"], "trades")))
    store.seal()
    export(args, now=NOW+timedelta(days=1))
    bundle = load_bundle(args.out)
    trade, = [r for r in bundle.records if r.kind == "trade"]
    assert decode(trade).outcome == "NO" and decode(trade).traded_at == NOW+timedelta(seconds=10)
    rows = [r for r in bundle.records if r.kind == "coverage" and r.condition_id == trade.condition_id]
    assert any(decode(r).trade_stream_ok for r in rows)
    assert not decode(rows[-1]).trade_stream_ok
    assert all((decode(r).valid_until_utc-r.captured_at).total_seconds() <= 30 for r in rows)


@pytest.mark.parametrize("fault", ["open_day", "unsealed", "changed", "byte_cap", "overlap"])
def test_refusal_leaves_source_untouched_and_no_completed_bundle(tmp_path, monkeypatch, fault):
    args, _, segment = args_for(tmp_path)
    now = NOW+timedelta(days=1)
    if fault == "open_day":
        now = NOW
    elif fault == "unsealed":
        (segment/"manifest.json").unlink()
    elif fault == "changed":
        monkeypatch.setattr(ExportReader, "recheck", lambda self: (_ for _ in ()).throw(ValueError("changed")))
    elif fault == "byte_cap":
        args.max_output_bytes = 10
    else:
        args.out = args.data_root/"bad"
    before = {p: p.read_bytes() for p in args.data_root.rglob("*") if p.is_file()}
    with pytest.raises(Exception):
        export(args, now=now)
    assert not args.out.exists()
    assert before == {p: p.read_bytes() for p in args.data_root.rglob("*") if p.is_file()}


def test_cli_closed_fixture_command_and_measured_size(tmp_path, capsys):
    args, _, _ = args_for(tmp_path, minutes=2)
    # CLI clock is injected only in test; the normal command uses current UTC.
    import weather.market.maker_replay_bundle as module
    original = module.export
    from unittest.mock import patch
    with patch.object(module, "export", lambda a: original(a, now=NOW+timedelta(days=1))):
        assert main(["bundle", "--date", args.date, "--data-root", str(args.data_root),
                     "--out", str(args.out), "--markets", "nyc"]) == 0
    assert "EXPORTED_FOR_DIAGNOSTICS" in capsys.readouterr().out
    sizes = {p.name: p.stat().st_size for p in args.out.iterdir()}
    print("SYNTHETIC_EXPORT_BYTES", json.dumps(sizes, sort_keys=True))


def test_later_settlement_day_uses_hash_bound_carry_without_new_books(tmp_path):
    from tests.market.test_maker_plugin import fixture, ledger
    from tests.market.test_maker_plugin_dry_run import jsonl
    args, _, _ = args_for(tmp_path)
    export(args, now=NOW+timedelta(days=1))
    prior = args.out
    _, rows, spec, target, _, _ = fixture(lead=1, now=NOW)
    fact = ledger(rows, spec, target)
    jsonl(args.data_root/"settlements"/"nyc"/"ledger.jsonl", [fact])
    args.date = fact["recorded_at_utc"][:10]
    args.carry_bundle = [prior]
    args.out = tmp_path/"settled"
    export(args, now=NOW+timedelta(days=4))
    bundle = load_bundle(args.out)
    facts = [decode(r) for r in bundle.records if r.kind == "settlement"]
    assert len(facts) == 3 and sum(f.p_yes for f in facts) == 1
    assert all(f.reconciliation_status == "match" for f in facts)
    assert all(c.active_from == c.active_until for c in bundle.conditions)
    assert not any(r.kind == "book" for r in bundle.records)


def test_streamed_inputs_are_hashed_and_early_stops_are_labelled(tmp_path):
    import hashlib
    source = tmp_path/"ledger.jsonl"
    source.write_bytes(b'{"a": 1}\n{"b": 2}\n')
    reader = ExportReader(tmp_path, 60, 1024**2)
    reader.lines(source, lambda line: True)
    assert reader.hashes["ledger.jsonl"].startswith("prefix:")
    reader.lines(source, lambda line: False)
    assert reader.hashes["ledger.jsonl"] == hashlib.sha256(source.read_bytes()).hexdigest()
    reader.lines(source, lambda line: True)  # A later partial read never replaces a whole-file hash.
    assert reader.hashes["ledger.jsonl"] == hashlib.sha256(source.read_bytes()).hexdigest()
    source.write_bytes(b'{"a": 1}\n{"b": 3}\n{"c": 4}\n')
    with pytest.raises(ValueError, match="source_changed_between_reads"):
        reader.read(source)


def record_trades(args, prints):
    """Production writer: each (capture offset s, venue offset ms from capture) is one sealed print."""
    when = NOW
    store = EvidenceStore(args.data_root/"maker_evidence", clock=lambda: when)
    for index, (captured, lead_ms) in enumerate(prints):
        when = NOW + timedelta(seconds=captured)
        venue = int(when.timestamp()) * 1000 + int(when.microsecond / 1000) + lead_ms
        store.record("trades", encoded(dict(event_type="last_trade_price", asset_id="101", id=f"t{index}",
                     market="0x"+f"{1:064x}", timestamp=str(venue), price=".47", size="10", side="SELL")))
    store.seal()


def test_small_venue_clock_lead_is_accepted_recorded_and_available_only_at_capture(tmp_path):
    from maker_core.replay.calibration import _trades
    args, _, _ = args_for(tmp_path)
    # A print captured at 15:20:59.5 whose venue clock reads 15:21:00.7, and an ordinary late print.
    record_trades(args, [(30, -300), (59.5, 1200)])
    summary = export(args, now=NOW+timedelta(days=1))
    skew = summary["trade_clock_skew"]
    assert skew["bound_us"] == 5_000_000 and skew["trades"] == 2 and skew["clamped_to_capture"] == 1
    assert (skew["min_us"], skew["max_us"], skew["p50_us"], skew["p999_us"]) == (-300_000, 1_200_000, -300_000, 1_200_000)
    bundle = load_bundle(args.out)
    early, lead = sorted((r for r in bundle.records if r.kind == "trade"), key=lambda r: r.captured_at)
    # Availability is the capture clock; the venue clock is kept exactly as recorded.
    assert lead.captured_at == NOW+timedelta(seconds=59.5) and early.captured_at == NOW+timedelta(seconds=30)
    assert decode(lead).traded_at == NOW+timedelta(seconds=60.7) > lead.captured_at
    assert decode(early).traded_at == NOW+timedelta(seconds=29.7)
    # The calibration numerator places the leading print in its capture minute, never the venue minute.
    occupied, invalid = _trades([bundle], lambda: None)
    assert {minute for _, minute in occupied} == {NOW} and not invalid
    receipt = json.loads((args.out/"export.json").read_bytes())
    assert receipt["trade_clock_skew"] == skew


@pytest.mark.parametrize("lead_ms", [5001, 60_000])
def test_venue_clock_lead_beyond_the_bound_refuses_the_day(tmp_path, lead_ms):
    args, _, _ = args_for(tmp_path)
    record_trades(args, [(30, 5000), (40, lead_ms)])
    with pytest.raises(ValueError, match="future_public_trade_clock"):
        export(args, now=NOW+timedelta(days=1))
    assert not args.out.exists()


def test_loader_admits_the_bounded_lead_and_refuses_beyond_it():
    from maker_core.replay.bundle import BundleError, CapturedRecord
    def row(lead):
        payload = dict(trade_id="t", outcome="YES", price=".5", size="1", aggressor_side="BUY",
                       traded_at_utc=(NOW+lead).isoformat())
        return CapturedRecord(0, NOW, "c", "trade", payload, "0"*64, {})
    assert decode(row(timedelta(seconds=5))).traded_at == NOW+timedelta(seconds=5)
    with pytest.raises(BundleError, match="trade_clock_skew_exceeds_bound"):
        decode(row(timedelta(seconds=5, microseconds=1)))
