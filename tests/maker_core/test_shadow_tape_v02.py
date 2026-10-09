"""Shadow tape v0.2 raw-record stream: replay-v2 bundle round trip, sequences, clocks, seal, scorer compatibility.

Guards: maker shadow tape v0.2 record stream and day bundle (docs/operations/maker-shadow-runner.md, Tape v0.2
  record stream): receipt-time stamping with the mid-minute book refresh (no capture gap under an advancing
  clock), the recorder fault boundary, the trade baseline across the UTC day roll and the Gamma/reward
  allowlists; round trip against the vendored replay-v2 reader contract
  (tests/maker_core/fixtures/replay_v2_reader_contract.py, pinned to build-line 2d8cccb13).
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import json
import random
import socket
import types

import pytest

from maker_core.evidence.journal import verify_journal
from maker_core.shadow import tape
from maker_core.shadow.records import (BUNDLE_FORMAT, SHADOW_REPLAY_LIMITS, RawRecorder, RecordingReads,
                                       RecordStream, bundle_day, day_active_intervals, day_directory,
                                       gamma_market_projection, group_id, records_summary, reward_projection)
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
    assert rows[1]["raw"]["fault"] == "minute:RuntimeError" and seal["records_stream"]["records"] == 0
    assert seal["records_stream"]["status"] == "ok"


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
        legacy_minute = runner.step(NOW, MARKETS)
        legacy_minute.pop("own_size_mid", None)  # a tape written before #267 has no OD23 counts
        legacy.record("minute", NOW, **legacy_minute)
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


class AdvancingReads(Reads):
    """Every public read advances the shared clock by its latency (fixed, or seeded jitter)."""

    def __init__(self, latency, **kwargs):
        super().__init__(**kwargs)
        self.latency, self.clock = latency, None

    def _tick(self):
        self.clock.now += timedelta(seconds=self.latency())

    def book(self, asset_id):
        self._tick()
        return super().book(asset_id)

    def reward_terms(self, condition_id):
        self._tick()
        return super().reward_terms(condition_id)

    def trades(self, condition_id):
        self._tick()
        return super().trades(condition_id)


def advancing_hour(tmp_path, latency, *, prints=None, refresh=True):
    inner = AdvancingReads(latency)
    runner, reads, _, clock = recording_rig(tmp_path, inner)
    inner.clock = clock
    writer = TapeWriter(tmp_path / "tapes", clock=clock, scope={"mode": "fixture"}, run_id="adv",
                        recorder=RawRecorder(reads, market_id=lambda slug: "fixture-market"))
    nows = []
    for n in range(60):
        minute = NOW + timedelta(minutes=n)
        clock.now = max(clock.now, minute)
        if n % 15 == 0:
            clock.now += timedelta(seconds=4)  # the runner's Gamma rediscovery delays that minute's reads
        if prints and n in prints:
            inner.prints[CONDITION] = prints[n](clock.now)
        reads.poll([CONDITION])
        payload = runner.step(minute, MARKETS)
        nows.append(inputs_from(payload["conditions"][0]["inputs"]))
        writer.record("minute", minute, **payload)
        if refresh:
            clock.now = max(clock.now, minute + timedelta(seconds=30))
            writer.poll([CONDITION])
    writer.close("completed")
    path, _ = bundle_day(tmp_path / "tapes", DAY, clock=lambda: AFTER_DAY)
    return reader.StreamBundle(path.parent), nows, inner


@pytest.mark.parametrize("jitter", [False, True], ids=["fixed_190ms", "jittered"])
def test_receipt_stamped_hour_under_an_advancing_clock_has_no_capture_gap(tmp_path, jitter):
    rng = random.Random(20261009)
    latency = (lambda: rng.uniform(0.05, 1.5)) if jitter else (lambda: 0.19)  # jitter: seeded, long tail
    prints = {n: (lambda at, n=n: [wallet_print(at - timedelta(seconds=2), f"0xc{n}")]) for n in range(5, 60, 7)}
    bundle, shadows, inner = advancing_hour(tmp_path, latency, prints=prints)
    records = list(bundle.records())
    assert all(reader.decode_record(r)[1] is None for r in records)  # nothing the real decoder would pop
    books = [r.captured_at for r in records if r.kind == "book"]
    assert max(b - a for a, b in zip(books, books[1:])) < timedelta(seconds=60)
    for r in records:
        if r.kind == "book":
            assert reader.decode(r).as_of_utc == r.captured_at  # receipt stamped
        if r.kind == "coverage":  # the window starts at the poll's receipt, never at a later decision instant
            assert reader.decode(r).valid_until_utc - r.captured_at == timedelta(seconds=60)
    decisions = {s.now for s in shadows}
    assert not decisions & {r.captured_at for r in records if r.kind in ("book", "coverage", "trade")}
    states = reader.replay_states(bundle)
    ordered = sorted(states.items())
    first = next(i for i, (_, state) in enumerate(ordered) if state[0])
    assert ordered[first][0][0] - NOW < timedelta(seconds=40)  # covered from the first mid-minute refresh
    gaps = [(at, state[1]) for (at, _), state in ordered[first:] if not state[0]]
    assert gaps == []  # no CAPTURE_GAP / TRADE_CAPTURE_GAP on an unchanged book for the rest of the hour
    for shadow in shadows[1:]:
        covered, reason, latest = states[(shadow.now, CONDITION)]
        assert (covered, reason) == (True, "COVERED")
        public = book_from_public(inner.books[YES], inner.books[NO], CONDITION, latest["book"].as_of_utc)
        assert latest["book"] == public and shadow.now - latest["book"].as_of_utc < timedelta(seconds=60)
        assert (compose_book(replace(public, as_of_utc=shadow.book.as_of_utc), shadow.existing)
                if compose_book else replace(public, as_of_utc=shadow.book.as_of_utc)) == shadow.book
        assert ((latest["terms"].min_size, latest["terms"].max_spread_cents, latest["terms"].rate_per_day)
                == (shadow.terms.min_size, shadow.terms.max_spread_cents, shadow.terms.rate_per_day))
    trades = [r for r in records if r.kind == "trade"]
    assert len(trades) == len(prints)  # the first poll (no prints) is the baseline; every later print is kept
    # Control: without the mid-minute book refresh the same hour shows CAPTURE_GAP after each slow minute start.
    control, _, _ = advancing_hour(tmp_path / "control", latency, prints=prints, refresh=False)
    assert "CAPTURE_GAP" in {state[1] for state in reader.replay_states(control).values()}


def test_malformed_print_timestamp_marks_the_poll_not_ok_and_the_run_goes_on(tmp_path):
    runner, _, _, clock = recording_rig(tmp_path)
    bad = wallet_print(NOW + timedelta(seconds=40), "0xbad")
    bad["timestamp"] = "not-a-time"
    good = wallet_print(NOW + timedelta(seconds=41), "0xd1")
    writer, seal = record_run(tmp_path, runner, clock, 3, mid=False, prints={1: [bad, good]})
    rows = [r for r in sealed_tapes(tmp_path / "tapes", DAY)[0][0]["rows"] if r["event"] == "minute"]
    assert len(rows) == 3 and all("fault" not in r["raw"] for r in rows)
    folder = day_directory(tmp_path / "tapes", DAY)
    records = [json.loads(line) for line in next(folder.glob("*-records.jsonl")).read_text().splitlines()]
    assert [r["payload"]["venue"]["transactionHash"] for r in records if r["kind"] == "trade"] == ["0xd1"]
    assert [r["payload"]["trade_stream_ok"] for r in records if r["kind"] == "coverage"] == [True, False, False]
    assert seal["records_stream"]["status"] == "ok"


def test_fsync_failure_marks_the_stream_broken_and_never_stops_the_runner(tmp_path, monkeypatch):
    from maker_core.shadow import records
    runner, _, _, clock = recording_rig(tmp_path)
    calls = {"n": 0}

    def fsync(fd):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise OSError(28, "fixture: no space left")
    monkeypatch.setattr(records, "os", types.SimpleNamespace(fsync=fsync))
    writer, seal = record_run(tmp_path, runner, clock, 3, mid=False)
    rows = [r for r in sealed_tapes(tmp_path / "tapes", DAY)[0][0]["rows"] if r["event"] == "minute"]
    assert len(rows) == 3 and "fault" not in rows[0]["raw"]
    assert rows[1]["raw"]["fault"] == "write:OSError" and rows[2]["raw"]["broken"] == "write:OSError"
    stream_seal = json.loads(next(day_directory(tmp_path / "tapes", DAY).glob("*-records.seal.json")).read_bytes())
    assert stream_seal["status"] == "broken" and stream_seal["broken_reason"] == "write:OSError"
    assert stream_seal["faults"] == {"write:OSError": 1} and seal["records_stream"]["status"] == "broken"
    assert records_summary(tmp_path / "tapes", DAY)["broken_streams"] == [stream_seal["stream"]]
    with pytest.raises(ValueError, match="broken_record_stream"):
        bundle_day(tmp_path / "tapes", DAY, clock=lambda: AFTER_DAY)


def test_trade_baseline_carries_across_the_utc_day_roll(tmp_path):
    runner, _, _, clock = recording_rig(tmp_path)
    start = (NOW - timedelta(days=1)).replace(hour=23, minute=58)  # the roll into DAY (no later dates)
    late = wallet_print(start + timedelta(minutes=1, seconds=45), "0xe1")  # 23:59:45, first polled at 00:00
    record_run(tmp_path, runner, clock, 4, start=start, prints={2: [late]})
    root, previous_day = tmp_path / "tapes", start.date().isoformat()
    day_one, _ = bundle_day(root, previous_day, clock=lambda: AFTER_DAY - timedelta(days=1))
    day_two, _ = bundle_day(root, DAY, clock=lambda: AFTER_DAY)
    assert not [r for r in reader.StreamBundle(day_one.parent).records() if r.kind == "trade"]
    bundle = reader.StreamBundle(day_two.parent)
    trades = [r for r in bundle.records() if r.kind == "trade"]
    assert [(r.payload["traded_at_utc"], r.captured_at) for r in trades] == [
        ((start + timedelta(minutes=1, seconds=45)).isoformat(), start + timedelta(minutes=2))]
    states = reader.replay_states(bundle)
    # The day's first record re-states the last descriptor, so the new day's first minute is covered.
    assert states[(start + timedelta(minutes=2), CONDITION)][:2] == (True, "COVERED")


def test_gamma_and_reward_records_are_allowlisted(tmp_path):
    address = "0x" + "3" * 40
    market = {"conditionId": CONDITION, "slug": "fixture-band", "submitted_by": address, "resolvedBy": address,
              "description": "fixture", "bestBid": 0.49, "question": f"fixture {address}",
              "clobRewards": [{"rewardsDailyRate": 100, "assetAddress": address, "id": "7"}]}
    projected, dropped = gamma_market_projection(market)
    assert projected == {"conditionId": CONDITION, "slug": "fixture-band", "bestBid": 0.49,
                         "clobRewards": [{"rewardsDailyRate": 100}]}
    assert dropped == 4  # submitted_by, resolvedBy, description, and the address-like question
    record = {"condition_id": CONDITION, "rewards_max_spread": 5, "rewards_min_size": 20, "maker": address,
              "rewards_config": [{"rate_per_day": 100, "start_date": "2026-09-01", "end_date": "2500-12-31",
                                  "asset_address": address, "id": 3}]}
    assert reward_projection(record) == {
        "condition_id": CONDITION, "rewards_max_spread": 5, "rewards_min_size": 20,
        "rewards_config": [{"rate_per_day": 100, "start_date": "2026-09-01", "end_date": "2500-12-31"}]}

    class GammaReads(Reads):
        def events(self, slugs):
            return [{"slug": "highest-temperature-in-fixture", "id": "9", "negRisk": True, "markets": [market]}]
    runner, reads, _, clock = recording_rig(tmp_path, GammaReads(rewards={CONDITION: record}))
    reads.events(["highest-temperature-in-fixture"])
    record_run(tmp_path, runner, clock, 1)
    raw = next(day_directory(tmp_path / "tapes", DAY).glob("*-records.jsonl")).read_bytes()
    assert address.encode() not in raw and b"submitted_by" not in raw and b'"dropped_keys":4' in raw


def test_shadow_replay_limits_are_pinned_above_a_24_band_day():
    assert SHADOW_REPLAY_LIMITS == {"max_records": 600_000, "max_bytes": 1024**3, "max_seconds": 900.0}
