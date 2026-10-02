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
    assert skew["bound_us"] == 5_000_000 and skew["trades"] == 2 and skew["leading_capture"] == 1
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


def reward_body(cid, rate):
    return {"data": [{"condition_id": cid, "rewards_min_size": 20, "rewards_max_spread": 5, "rewards_config": [
        {"rate_per_day": rate, "start_date": NOW.date().isoformat(), "end_date": NOW.date().isoformat()}]}]}


def record_rewards(args, changes):
    """Production writer: (seconds after NOW, condition number, rate) reward captures in one sealed segment."""
    when = NOW
    store = EvidenceStore(args.data_root/"maker_evidence", clock=lambda: when)
    for seconds, number, rate in changes:
        when = NOW + timedelta(seconds=seconds)
        store.record("rewards", encoded(reward_body("0x"+f"{number:064x}", rate)), metadata={"http_status": 200})
    store.seal()


def export_bytes(args, out):
    args.out = out
    summary = export(args, now=NOW+timedelta(days=1))
    return summary, {p.name: p.read_bytes() for p in out.iterdir()}


def test_calibration_export_skips_reward_terms_and_is_byte_identical(tmp_path, monkeypatch):
    import weather.market.maker_replay_bundle as module
    args, _, _ = args_for(tmp_path, minutes=3)
    record_rewards(args, [(400, 1, 50), (460, 2, 70)])
    args.kinds = module.CALIBRATION_KINDS
    calls, original = [], module.reward_terms
    monkeypatch.setattr(module, "reward_terms", lambda *a: calls.append(a) or original(*a))
    summary, files = export_bytes(args, tmp_path/"skipped")
    assert not calls
    # The former path evaluated terms and then dropped them by kind: same bytes and counts.
    monkeypatch.setattr(module.Projection, "keeps", lambda self, kind: True)
    forced, forced_files = export_bytes(args, tmp_path/"evaluated")
    assert calls and files == forced_files and summary["counts"] == forced["counts"]
    assert "terms" not in summary["counts"]


def test_panel_terms_from_named_cids_and_newest_rows_equal_the_full_scan(tmp_path, monkeypatch):
    from weather.market.maker_plugin_runner import CaptureIndex
    args, _, _ = args_for(tmp_path, minutes=3)
    # Rate changes for single conditions, two at one clock, and an unchanged repeat.
    record_rewards(args, [(400, 1, 50), (460, 2, 70), (460, 3, 80), (520, 1, 50), (580, 3, 90)])
    summary, files = export_bytes(args, tmp_path/"named")
    assert summary["counts"]["terms"] > 3
    monkeypatch.setattr(CaptureIndex, "reward_cids", lambda self, now: None)
    monkeypatch.setattr(CaptureIndex, "newest_reward_rows", CaptureIndex.reward_rows)
    full, full_files = export_bytes(args, tmp_path/"full")
    assert files == full_files and summary["counts"] == full["counts"]


def test_capture_index_bisect_lookups_equal_linear_scans():
    import hashlib
    from weather.market.maker_plugin.inputs import latest
    from weather.market.maker_plugin_runner import CaptureIndex, reward_terms
    a, b = "0x"+f"{1:064x}", "0x"+f"{2:064x}"
    rows = [(0, a, 10), (30, a, 20), (30, a, 20), (30, b, 5), (90, a, 30), (150, b, 6)]
    def capture(sequence, seconds, raw):
        return dict(kind="rewards", sequence=sequence, captured_at_utc=(NOW+timedelta(seconds=seconds)).isoformat(),
                    http_status=200, body_stored=True, body_utf8=raw,
                    response_sha256=hashlib.sha256(raw.encode()).hexdigest())
    captures = [capture(i, t, json.dumps(reward_body(cid, rate))) for i, (t, cid, rate) in enumerate(rows)]
    index = CaptureIndex(captures)
    def linear(cid, now):  # The former full scan, in capture order.
        return [dict(captured_at_utc=c["captured_at_utc"], record=reward_body(r_cid, rate)["data"][0])
                for c, (t, r_cid, rate) in zip(captures, rows) if r_cid == cid and NOW+timedelta(seconds=t) <= now]
    for seconds in (-1, 0, 29, 30, 31, 90, 149, 150, 400):
        now = NOW + timedelta(seconds=seconds)
        for cid in (a, b, "0x"+f"{9:064x}"):
            expected = linear(cid, now)
            assert index.reward_rows(cid, now) == expected
            newest = max((r["captured_at_utc"] for r in expected), default=None)
            assert index.newest_reward_rows(cid, now) == [r for r in expected if r["captured_at_utc"] == newest]
            terms = reward_terms(index, cid, now)
            assert (terms is None) == (not expected)
            if expected:
                assert terms.as_of_utc.isoformat() == latest(expected, now)["captured_at_utc"]
    assert index.reward_cids(NOW) == {a} and index.reward_cids(NOW+timedelta(seconds=30)) == {a, b}
    assert index.reward_cids(NOW+timedelta(seconds=31)) == set()
    corrupt = CaptureIndex([*captures, capture(6, 60, "not json")])
    assert corrupt.reward_cids(NOW+timedelta(seconds=30)) == {a, b}
    assert corrupt.reward_cids(NOW+timedelta(seconds=60)) is None  # Malformed: every cid is looked up.
    with pytest.raises(ValueError, match="captured_rewards_malformed"):
        corrupt.reward_rows(a, NOW+timedelta(seconds=60))
