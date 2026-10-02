from datetime import timedelta
import json
import socket

import pytest
from maker_core.replay.bundle import load_bundle, timestamp
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


def _skewed_trades(args, prints, *, trade_id=None):
    """Production-writer captures: each (capture, venue) pair is one venue trade captured at ``capture``."""
    when = NOW + timedelta(seconds=5)
    store = EvidenceStore(args.data_root/"maker_evidence", clock=lambda: when)
    store.event("stream_lifecycle", dict(state="connected", channel="trades",
                subscription=store.subscription(["100", "101"], "trades")))
    for when, venue in prints:
        trade = dict(event_type="last_trade_price", asset_id="101", market="0x"+f"{1:064x}",
                     timestamp=str(int(venue.timestamp()*1000)), price=".47", size="10", side="SELL")
        if trade_id is not None:
            trade["id"] = trade_id
        store.record("trades", encoded(trade))
    store.seal()


def test_small_venue_clock_lead_is_clamped_to_capture_and_recorded(tmp_path):
    args, _, _ = args_for(tmp_path)
    venue = NOW + timedelta(seconds=10)
    first_capture = venue - timedelta(milliseconds=1200)
    # The same venue trade re-delivered later must not become a conflicting duplicate.
    _skewed_trades(args, [(first_capture, venue), (venue - timedelta(milliseconds=200), venue)], trade_id="t-1")
    summary = export(args, now=NOW+timedelta(days=1))
    rows = [r for r in load_bundle(args.out).records if r.kind == "trade"]
    assert len(rows) == 2
    first = decode(rows[0])
    assert rows[0].captured_at == first_capture and first.traded_at == first_capture
    assert all(decode(r) == first for r in rows)  # Identical, so the engine and calibration dedupe it.
    assert all(timestamp(r.payload["venue_traded_at_utc"]) == venue for r in rows)
    assert summary["counts"]["trade_clock_clamped"] == 2
    skew = summary["trade_clock_skew"]
    assert skew == dict(bound_ms=5000, trades=2, clamped=2, max_ms=1200, p50_ms=200, p90_ms=1200, p99_ms=1200)
    assert json.loads((args.out/"export.json").read_text())["trade_clock_skew"] == skew


def test_trade_availability_never_precedes_capture(tmp_path):
    args, _, _ = args_for(tmp_path)
    base = NOW + timedelta(seconds=10)
    leads = (timedelta(milliseconds=4999), timedelta(0), timedelta(milliseconds=-800))
    _skewed_trades(args, [(base + timedelta(seconds=i), base + timedelta(seconds=i) + lead)
                          for i, lead in enumerate(leads)])
    summary = export(args, now=NOW+timedelta(days=1))
    rows = [r for r in load_bundle(args.out).records if r.kind == "trade"]
    assert [r.captured_at for r in rows] == [base + timedelta(seconds=i) for i in range(3)]
    for row, lead in zip(rows, leads):
        trade = decode(row)
        assert trade.traded_at == min(row.captured_at + lead, row.captured_at) <= row.captured_at
    # A venue clock at or behind capture is kept exactly as recorded, with no clamp field.
    assert ["venue_traded_at_utc" in r.payload for r in rows] == [True, False, False]
    assert summary["counts"]["trade_clock_clamped"] == 1
    assert summary["trade_clock_skew"]["max_ms"] == 4999


def test_large_venue_clock_lead_refuses(tmp_path):
    args, _, _ = args_for(tmp_path)
    capture = NOW + timedelta(seconds=10)
    _skewed_trades(args, [(capture, capture + timedelta(seconds=5, milliseconds=1))])
    with pytest.raises(ValueError, match="future_public_trade_clock"):
        export(args, now=NOW+timedelta(days=1))
    assert not args.out.exists()
