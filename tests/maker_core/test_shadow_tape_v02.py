"""Shadow tape v0.2 raw-record stream: replay-v2 bundle round trip, sequences, clocks, seal, scorer compatibility.

Guards: maker shadow tape v0.2 record stream and day bundle (docs/operations/maker-shadow-runner.md, Tape v0.2
  record stream); round trip against the vendored replay-v2 reader contract
  (tests/maker_core/fixtures/replay_v2_reader_contract.py, pinned to build-line 2d8cccb13).
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import json
import socket

import pytest

from maker_core.evidence.journal import verify_journal
from maker_core.shadow import tape
from maker_core.shadow.records import (BUNDLE_FORMAT, RawRecorder, RecordingReads, RecordStream, bundle_day,
                                       day_active_intervals, day_directory, group_id, records_summary)
from maker_core.shadow.runner import book_from_public
from maker_core.shadow.score import score_day
from maker_core.shadow.tape import (SEAL_SCHEMA, SEAL_SCHEMA_V01, TAPE_SCHEMA, TAPE_SCHEMA_V01, TapeWriter,
                                    inputs_from, seal_digest, sealed_tapes)

from .fixtures import replay_v2_reader_contract as reader
from .fixtures.shadow_rig import CONDITION, MARKETS, NO, NOW, YES, Reads, data_print, rig

try:  # #267 (compose-align): the decision book is the public book with the shadow's own resting legs on it.
    from maker_core.quoting.book import compose_book
except ImportError:  # before #267 the decision book is the public book
    compose_book = None

DAY = NOW.date().isoformat()
AFTER_DAY = datetime(2026, 9, 29, 0, 5, tzinfo=timezone.utc)
WALLET_FIELDS = ("proxyWallet", "name", "pseudonym", "profileImage", "bio")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("shadow test attempted network")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


class Panel:
    def __init__(self):
        self.covered = (YES, NO)

    def covers(self, asset):
        return asset in self.covered

    def mid(self, asset, at):
        return D(".50")

    def prints(self, asset, start, end):
        return []


def recording_rig(tmp_path, inner=None):
    inner = inner or Reads()
    reads = RecordingReads(inner, None)
    runner, gate, port, clock, book = rig(tmp_path, reads=reads)
    reads.clock = clock
    return runner, reads, inner, clock


def record_run(tmp_path, runner, clock, minutes, *, start=NOW, run_id="r1", mid=True, close=True, prints=None):
    reads = runner.reads
    writer = TapeWriter(tmp_path / "tapes", clock=clock, scope={"mode": "fixture"}, run_id=run_id,
                        recorder=RawRecorder(reads, market_id=lambda slug: "fixture-market"))
    for n in range(minutes):
        clock.now = start + timedelta(minutes=n)
        if prints and n in prints:
            reads.reads.prints[CONDITION] = prints[n]
        reads.poll([CONDITION])
        writer.record("minute", clock.now, **runner.step(clock.now, MARKETS))
        if mid:
            clock.now = start + timedelta(minutes=n, seconds=30)
            writer.poll([CONDITION])
    seal = writer.close("completed") if close else None
    return writer, seal


def wallet_print(at, tx, price="0.50", size="10", asset=YES):
    row = data_print(asset, at, price, size, tx=tx)
    row.update(proxyWallet="0x" + "9" * 40, name="fixture-user", pseudonym="Fixture-Person", bio="fictional")
    return row


def test_v02_tape_round_trips_into_replay_v2_reader_contract(tmp_path):
    runner, _, inner, clock = recording_rig(tmp_path)
    prints = {1: [wallet_print(NOW + timedelta(seconds=50), "0xa1")],
              2: [wallet_print(NOW + timedelta(seconds=50), "0xa1"),
                  wallet_print(NOW + timedelta(seconds=115), "0xa2", asset=NO, price="0.49")]}
    record_run(tmp_path, runner, clock, 4, prints=prints)
    root = tmp_path / "tapes"
    path, manifest = bundle_day(root, DAY, clock=lambda: AFTER_DAY)
    assert manifest["format"] == BUNDLE_FORMAT and manifest["provenance"] == "captured"
    assert manifest["coverage_groups"] == [{"group_id": group_id(CONDITION), "condition_ids": [CONDITION]}]
    assert manifest["conditions"] == [{"condition_id": CONDITION, "market_id": "fixture-market",
                                       "domain_id": "weather", "active_from": NOW.isoformat(),
                                       "active_until": (NOW + timedelta(minutes=4)).isoformat()}]

    bundle = reader.StreamBundle(path.parent)
    states = reader.replay_states(bundle)
    tapes, unsealed = sealed_tapes(root, DAY)
    assert unsealed == [] and tapes[0]["tape_schema"] == TAPE_SCHEMA
    minutes = [r for r in tapes[0]["rows"] if r["event"] == "minute"]
    assert len(minutes) == 4
    for row in minutes:
        recorded = row["conditions"][0]
        assert row["raw"]["records"] > 0 and row["raw"]["dropped"] == {}
        shadow = inputs_from(recorded["inputs"])
        covered, reason, latest = states[(shadow.now, CONDITION)]
        # Every shadow condition-minute is a covered replay instant with the shadow's exact inputs.
        assert (covered, reason) == (True, "COVERED")
        # The tape records the PUBLIC book; the decision book is derived from it and the resting legs.
        public = book_from_public(inner.books[YES], inner.books[NO], CONDITION, shadow.book.as_of_utc)
        assert latest["book"] == public
        assert (compose_book(public, shadow.existing) if compose_book else public) == shadow.book
        assert latest["terms"] == shadow.terms
        assert latest["descriptor"].market == shadow.market and latest["descriptor"].horizon_days == 1
        assert latest["outcome_view"] == shadow.fair_value and latest["info_event"] == shadow.events
    # Mid-minute coverage keeps the trade stream continuous between decision instants.
    mids = [at for (at, _), _ in states.items() if at.second == 30]
    assert len(mids) == 4
    trades = [r for r in bundle.records() if r.kind == "trade"]
    assert [(r.payload["outcome"], r.payload["aggressor_side"]) for r in trades] == [("YES", "SELL"), ("NO", "SELL")]
    assert all(reader.decode(r).traded_at - r.captured_at <= reader.MAX_TRADE_CLOCK_SKEW for r in trades)
    raw = b"".join((path.parent / s["path"]).read_bytes() for s in manifest["streams"])
    for field in WALLET_FIELDS:
        assert field.encode() not in raw  # Public trade rows: no wallet or profile fields copied.


def test_first_trade_poll_is_a_baseline_and_continuity_loss_is_marked(tmp_path, monkeypatch):
    monkeypatch.setattr("maker_core.shadow.records.TRADES_PAGE", 2)
    runner, _, _, clock = recording_rig(tmp_path)
    old = [wallet_print(NOW - timedelta(minutes=5), "0xold")]
    full_page = [wallet_print(NOW + timedelta(seconds=55), "0xb1"), wallet_print(NOW + timedelta(seconds=56), "0xb2")]
    record_run(tmp_path, runner, clock, 2, mid=False, prints={0: old, 1: full_page})
    folder = day_directory(tmp_path / "tapes", DAY)
    rows = [json.loads(line) for line in next(folder.glob("*-records.jsonl")).read_text().splitlines()]
    trades = [r["payload"]["venue"]["transactionHash"] for r in rows if r["kind"] == "trade"]
    coverage = [r["payload"]["trade_stream_ok"] for r in rows if r["kind"] == "coverage"]
    assert trades == ["0xb1", "0xb2"]  # the pre-start print is a baseline, never emitted
    assert coverage == [True, False]  # a full page not reaching the previous newest print may have skipped prints


def test_sequences_unique_across_runs_and_bundle_refusals(tmp_path):
    runner, _, _, clock = recording_rig(tmp_path)
    root = tmp_path / "tapes"
    record_run(tmp_path, runner, clock, 2, run_id="r1")
    writer, _ = record_run(tmp_path, runner, clock, 2, run_id="r2", start=NOW + timedelta(minutes=10), close=False)
    with pytest.raises(ValueError, match="unsealed_record_stream"):
        bundle_day(root, DAY, clock=lambda: AFTER_DAY)
    writer.close("completed")
    with pytest.raises(ValueError, match="utc_day_not_closed"):
        bundle_day(root, DAY, clock=lambda: AFTER_DAY - timedelta(hours=1))
    seals = sorted((json.loads(p.read_bytes()) for p in day_directory(root, DAY).glob("*-records.seal.json")),
                   key=lambda s: s["first_sequence"])
    assert seals[0]["last_sequence"] < seals[1]["first_sequence"]
    assert day_active_intervals(root, DAY) == [
        (CONDITION, NOW, NOW + timedelta(minutes=2)),
        (CONDITION, NOW + timedelta(minutes=10), NOW + timedelta(minutes=12))]
    path, manifest = bundle_day(root, DAY, clock=lambda: AFTER_DAY)
    assert len(manifest["streams"]) == 2
    assert len({r.sequence for r in reader.StreamBundle(path.parent).records()}) == sum(s["records"] for s in seals)
    summary = records_summary(root, DAY)
    assert summary["unsealed_streams"] == [] and summary["kinds"]["descriptor"] == 2
    with pytest.raises(FileExistsError):
        bundle_day(root, DAY, clock=lambda: AFTER_DAY)


def test_clock_regression_outside_day_and_undescribed_group_are_dropped_and_counted(tmp_path):
    stream = RecordStream(tmp_path, DAY, "x")
    stream.register(CONDITION, market_id="m", domain_id="weather")
    sources = {"fixture": "0" * 64}
    early = stream.write([(NOW, group_id(CONDITION), "coverage", {"trade_stream_ok": True}, sources, True)])
    assert early["records"] == 0 and early["dropped"] == {"undescribed_group": 1}
    stream.write([(NOW + timedelta(minutes=1), CONDITION, "descriptor", {"a": 1}, sources, False)])
    late = stream.write([(NOW, CONDITION, "book", {"b": 1}, sources, False),
                         (NOW + timedelta(days=1), CONDITION, "book", {"b": 2}, sources, False)])
    assert late["records"] == 0 and late["dropped"] == {"out_of_order": 1, "outside_day": 1}
    seal = stream.close()
    assert seal["records"] == 1 and seal["dropped"] == {"out_of_order": 1, "outside_day": 1, "oversize": 0,
                                                        "undescribed_group": 1}


def test_recorder_fault_costs_raw_records_not_the_tape(tmp_path):
    runner, _, _, clock = recording_rig(tmp_path)
    writer = TapeWriter(tmp_path / "tapes", clock=clock, scope={}, run_id="r", recorder=RawRecorder(
        runner.reads, market_id=lambda slug: (_ for _ in ()).throw(RuntimeError("boom"))))
    writer.record("minute", NOW, **runner.step(NOW, MARKETS))
    seal = writer.close("completed")
    rows = sealed_tapes(tmp_path / "tapes", DAY)[0][0]["rows"]
    assert rows[1]["raw"] == {"error": "RuntimeError"} and seal["records_stream"]["records"] == 0


def test_terms_absence_is_recorded_and_replays_as_missing_terms(tmp_path):
    runner, _, _, clock = recording_rig(tmp_path, Reads(rewards={}))
    record_run(tmp_path, runner, clock, 2)
    path, _ = bundle_day(tmp_path / "tapes", DAY, clock=lambda: AFTER_DAY)
    terms = [r for r in reader.StreamBundle(path.parent).records() if r.kind == "terms"]
    assert len(terms) == 2 and all("absent" in r.payload for r in terms)
    states = reader.replay_states(reader.StreamBundle(path.parent))
    assert states[(NOW, CONDITION)][:2] == (False, "MISSING_TERMS")


def test_streaming_seal_equals_journal_verification_and_refuses_a_broken_chain(tmp_path):
    runner, _, _, clock = recording_rig(tmp_path)
    _, seal = record_run(tmp_path, runner, clock, 2)
    path = tmp_path / "tapes" / seal["tape"]
    rows = verify_journal(path, expected_digest=seal["sha256"])
    assert seal["schema_version"] == SEAL_SCHEMA and seal["records"] == len(rows) == 4
    assert seal_digest(path) == {k: seal[k] for k in ("sha256", "bytes", "records", "final_line_sha256")}
    lines = path.read_bytes().splitlines(keepends=True)
    broken = tmp_path / "broken.tape.jsonl"
    broken.write_bytes(b"".join(lines[:1] + lines[2:]))
    with pytest.raises(ValueError):
        seal_digest(broken)
    broken.write_bytes(b"".join(lines[:-1]))
    with pytest.raises(ValueError, match="terminal"):
        seal_digest(broken)


def test_scorer_reads_v01_and_v02_tapes_side_by_side(tmp_path, monkeypatch):
    runner, _, _, clock = recording_rig(tmp_path)
    with monkeypatch.context() as m:  # the v0.1 writer: same journal, v0.1 scope and seal, no record stream
        m.setattr(tape, "TAPE_SCHEMA", TAPE_SCHEMA_V01)
        m.setattr(tape, "SEAL_SCHEMA", SEAL_SCHEMA_V01)
        legacy = TapeWriter(tmp_path / "tapes", clock=clock, scope={"mode": "fixture"}, run_id="a-v01")
        legacy.record("minute", NOW, **runner.step(NOW, MARKETS))
        legacy.close("completed")
    runner.reads.take_polls()
    writer = TapeWriter(tmp_path / "tapes", clock=clock, scope={"mode": "fixture"}, run_id="b-v02",
                        recorder=RawRecorder(runner.reads, market_id=lambda slug: "fixture-market"))
    clock.now = NOW + timedelta(minutes=1)
    runner.reads.poll([CONDITION])
    payload = runner.step(clock.now, MARKETS)
    payload["own_size_mid"] = {"books_with_own_legs": 1, "mid_differs": 1}  # #267 field, fixture counts
    writer.record("minute", clock.now, **payload)
    writer.close("completed")
    tapes, unsealed = sealed_tapes(tmp_path / "tapes", DAY)
    assert unsealed == [] and [t["tape_schema"] for t in tapes] == [TAPE_SCHEMA_V01, TAPE_SCHEMA]
    assert tapes[0]["records_stream"] is None and tapes[1]["records_stream"]["records"] > 0
    report = score_day(tapes, Panel(), utc_day=DAY)
    assert [t["tape_schema"] for t in report["tapes"]] == [TAPE_SCHEMA_V01, TAPE_SCHEMA]
    assert report["strata"]["policy"]["condition_minutes"] == 2
    assert report["own_size_mid"] == {"books_with_own_legs": 1, "mid_differs": 1, "minutes_recorded": 1,
                                      "minutes_not_recorded": 1}
