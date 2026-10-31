"""Counterfactual fill tape exporter over synthetic 88a journals written by the real evidence store.

Guards: item 330 build 2 input contract (docs/operations/passive-maker-evidence-capture.md, "Counterfactual
  fill tape"): day-folder date filter before any open (reserved window 2026-09-30..10-15 never listed or opened),
  shared read/write/delete opens, create-only output with orphan set-aside, resume by day receipt, stat-only dry
  run, record compatibility with build 2's toxicity.read_records (copied contract, 4ae3602fa), point-in-time
  context (prints strictly before the instant, so a fill's own print is never its context), one fill rule per
  backlog, and a damaged gzip journal leaving only its own day unsealed.
"""
from __future__ import annotations

import builtins
from datetime import date, datetime, timedelta, timezone
import gzip
import hashlib
import io
import json
import os
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from weather.market import maker_counterfactual_tape as tape
from weather.market.maker_evidence_archive import compress_closed_segments
from weather.market.maker_evidence_store import EvidenceStore, WriterLock
from weather.market.market_config import event_slug_for_date

from tests.market import cf_tape_build2_contract as build2

COND_A, COND_B, COND_C = "0x" + "a" * 64, "0x" + "b" * 64, "0x" + "c" * 64
YES_A, NO_A, YES_B, NO_B, YES_C, NO_C = "111", "112", "221", "222", "331", "332"
DAY_LATE, DAY_EARLY = date(2026, 9, 28), date(2026, 9, 27)
RESERVED_DAY, AFTER_DAY = date(2026, 9, 30), date(2026, 10, 16)
FORBIDDEN = ("2026-09-30", "2026-10-16", ".writer.lock", "status.json", "book-331", "book-332")
UNSEALED = "15-0123456789ab"
STAMP_CLOCK = datetime(2026, 10, 17, 3, 55, tzinfo=timezone.utc)


def _book(asset, market, bid, ask, bid_size="100", ask_size="50"):
    return {"market": market, "asset_id": asset, "timestamp": "0", "hash": "x",
            "bids": [{"price": "0.01", "size": "10"}, {"price": bid, "size": bid_size}],
            "asks": [{"price": "0.99", "size": "10"}, {"price": ask, "size": ask_size}]}


def _bands(day):
    today, later = event_slug_for_date(day, "nyc"), event_slug_for_date(RESERVED_DAY, "nyc")
    return [{"condition_id": COND_A, "city": "nyc", "day_ahead": 0, "event_slug": today, "tokens": [YES_A, NO_A]},
            {"condition_id": COND_B, "city": "nyc", "day_ahead": 0, "event_slug": today, "tokens": [YES_B, NO_B]},
            # A band of an event dated inside the reserved window: dropped before its books are opened.
            {"condition_id": COND_C, "city": "nyc", "day_ahead": 2, "event_slug": later, "tokens": [YES_C, NO_C]}]


def _trade(asset, market, at, price, size, side="SELL"):
    return {"event_type": "last_trade_price", "asset_id": asset, "market": market, "price": price, "size": size,
            "side": side, "timestamp": str(int(at.timestamp() * 1000))}


def write_day(root, day, *, cycles=10, gz=False):
    """One sealed 88a segment: universe, both-side books every minute, and public prints."""
    clock = [datetime(day.year, day.month, day.day, 14, 0, 10, tzinfo=timezone.utc)]
    store = EvidenceStore(root, clock=lambda: clock[0])
    # Keep this synthetic archive fixture independent of whichever disk CI assigns.
    # The separate capture tests cover the free-space safety bands.
    store.free_bytes = lambda: 100 * 1024**3
    start = clock[0]
    for cycle in range(cycles):
        clock[0] = start + timedelta(minutes=cycle)
        store.event("universe", {"city": "nyc", "bands": _bands(day), "shortages": [], "missing_events": []},
                    partition="nyc")
        books = [_book(YES_A, COND_A, "0.40", "0.44"), _book(NO_A, COND_A, "0.55", "0.59"),
                 _book(YES_B, COND_B, "0.20", "0.25"), _book(NO_B, COND_B, "0.74", "0.79"),
                 _book(YES_C, COND_C, "0.30", "0.35"), _book(NO_C, COND_C, "0.64", "0.69")]
        store.record("books", json.dumps(books).encode(), metadata={"url": "fixture", "http_status": 200})
        clock[0] += timedelta(seconds=2)
    minute = start.replace(second=0) + timedelta(minutes=1)
    clock[0] = start + timedelta(minutes=cycles)
    fill = _trade(YES_A, COND_A, minute + timedelta(seconds=20), "0.40", "30")
    trades = [fill,
              _trade(NO_A, COND_A, minute + timedelta(seconds=30), "0.56", "5", "BUY"),   # above the NO bid
              _trade(YES_B, COND_B, minute + timedelta(seconds=10), "0.21", "7", "BUY"),  # above the B bid
              # At the fill instant on another band of the event: must not enter the fill's context.
              _trade(YES_B, COND_B, minute + timedelta(seconds=20), "0.22", "4", "BUY"),
              _trade(YES_C, COND_C, minute + timedelta(seconds=40), "0.30", "9")]         # reserved-dated event
    store.record("trades", json.dumps(trades).encode())
    store.record("trades", json.dumps([fill]).encode())   # an overlapping connection repeats the print
    store.seal()
    if gz:
        assert compress_closed_segments(store)
    return root / day.isoformat()


@pytest.fixture
def evidence(tmp_path):
    root = tmp_path / "maker_evidence"
    write_day(root, DAY_LATE, gz=True)      # gzip first: the archive compresses every sealed segment
    write_day(root, DAY_EARLY, cycles=3)
    write_day(root, RESERVED_DAY, cycles=2)
    write_day(root, AFTER_DAY, cycles=2)
    unsealed = root / DAY_LATE.isoformat() / "15-0123456789ab"
    unsealed.mkdir()
    (unsealed / "books.jsonl").write_bytes(b'{"offset":0}\n')
    (root / "notes").mkdir()
    (root / "status.json").write_text("{}", encoding="utf-8")
    (root / ".writer.lock").write_bytes(b"0")
    return root


class Recorder:
    """Every path the exporter lists, stats or opens."""

    def __init__(self, monkeypatch):
        self.paths = []
        real_scandir, real_open_input, real_open = os.scandir, tape.open_input, builtins.open
        real_stat, real_listdir = os.stat, os.listdir

        def scandir(path="."):
            self.paths.append(("list", os.fspath(path)))
            return real_scandir(path)

        def listdir(path="."):
            self.paths.append(("list", os.fspath(path)))
            return real_listdir(path)

        def stat(path, *args, **kwargs):
            self.paths.append(("stat", os.fspath(path) if not isinstance(path, int) else str(path)))
            return real_stat(path, *args, **kwargs)

        def open_input(path):
            self.paths.append(("open_input", os.fspath(path)))
            return real_open_input(path)

        def opener(file, *args, **kwargs):
            self.paths.append(("open", os.fspath(file) if not isinstance(file, int) else str(file)))
            return real_open(file, *args, **kwargs)

        monkeypatch.setattr(os, "scandir", scandir)
        monkeypatch.setattr(os, "listdir", listdir)
        monkeypatch.setattr(os, "stat", stat)
        monkeypatch.setattr(tape, "open_input", open_input)
        monkeypatch.setattr(builtins, "open", opener)

    def touched(self, needle):
        return [entry for entry in self.paths if needle in entry[1].replace("\\", "/")]


def _clock(start=STAMP_CLOCK):
    moments = [start]

    def now():
        moments[0] += timedelta(seconds=1)
        return moments[0]
    return now


def test_reserved_and_late_folders_are_never_listed_stat_or_opened(evidence, tmp_path, monkeypatch):
    recorder = Recorder(monkeypatch)
    receipt = tape.run(evidence, tmp_path / "out", now=_clock())
    assert receipt["input_days"] == [DAY_EARLY.isoformat(), DAY_LATE.isoformat()]
    assert receipt["folders_skipped_by_name"] == {"reserved_window_never_opened": 1, "after_max_date_never_opened": 1,
                                                  "not_a_day_folder": 3}
    for needle in FORBIDDEN:
        assert recorder.touched(needle) == [], needle
    # An unsealed segment is listed (to see that it has no manifest) and nothing inside it is opened.
    assert [kind for kind, _ in recorder.touched(UNSEALED)] == ["list"]
    # The allowed days were really read through the shared opener (so the recorder is live).
    assert recorder.touched(f"{DAY_LATE.isoformat()}/") and any(k == "open_input" for k, _ in recorder.paths)
    sealed = json.loads((tmp_path / "out" / "receipts" / f"{DAY_LATE.isoformat()}.json").read_text())
    assert sealed["match"] and sealed["unsealed_segments_skipped"] == 1
    assert sealed["dispositions"]["band_event_after_max_date"] == 10
    assert sealed["dispositions"]["book_ref_event_after_max_date_not_opened"] == 20
    assert sealed["dispositions"]["print_event_after_max_date_discarded"] == 1
    assert sealed["event_dates"] == [DAY_LATE.isoformat()]


@pytest.mark.parametrize("max_date", [date(2026, 9, 30), date(2026, 10, 15), date(2026, 10, 16)])
def test_requests_reaching_the_reserved_window_are_refused_before_listing(evidence, tmp_path, monkeypatch, max_date):
    recorder = Recorder(monkeypatch)
    with pytest.raises(tape.TapeRefused):
        tape.run(evidence, tmp_path / "out", max_date=max_date)
    with pytest.raises(tape.TapeRefused):
        tape.dry_run(evidence, tmp_path / "out", max_date=max_date)
    assert recorder.touched("maker_evidence") == []
    assert tape.main(["export", "--root", str(evidence), "--out-dir", str(tmp_path / "out"),
                      "--max-date", max_date.isoformat()]) == 2


def test_output_inside_the_input_or_data_tree_is_refused(evidence):
    with pytest.raises(tape.TapeRefused):
        tape.run(evidence, evidence / "tape-out")
    with pytest.raises(tape.TapeRefused):
        tape.run(evidence, tape.data_path("cf-tape"))


@pytest.mark.skipif(os.name != "nt", reason="Windows share modes")
def test_inputs_are_opened_sharing_read_write_and_delete(tmp_path):
    path = tmp_path / "journal.jsonl"
    path.write_bytes(b"one\n")
    with tape.open_input(path) as held:
        with open(path, "ab") as writer:     # a capture writer can append
            writer.write(b"two\n")
        moved = tmp_path / "journal.jsonl.moved"
        os.rename(path, moved)                # the archive can rename
        os.remove(moved)                      # and delete the plain copy after gzip
        assert held.read(4) == b"one\n"
    assert not moved.exists()


def test_export_takes_no_lock_and_runs_beside_a_live_writer_lock(evidence, tmp_path):
    with WriterLock(evidence):
        receipt = tape.run(evidence, tmp_path / "out", now=_clock())
        assert receipt["all_match"] and receipt["days_extracted"] == 2
    with WriterLock(evidence):   # still acquirable afterwards: nothing was left holding it
        pass


def test_dry_run_is_stat_only(evidence, tmp_path, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("dry run opened a file")
    recorder = Recorder(monkeypatch)
    for target, name in ((builtins, "open"), (io, "open"), (gzip, "open"), (tape, "open_input"), (os, "open")):
        monkeypatch.setattr(target, name, refuse)
    plan = tape.dry_run(evidence, tmp_path / "out")
    assert [row["utc_day"] for row in plan["days"]] == [DAY_LATE.isoformat(), DAY_EARLY.isoformat()]
    late = plan["days"][0]
    assert late["segments"] == 2 and late["sealed_segments"] == 1 and late["unsealed_segments"] == 1
    assert late["input_bytes"] > 0 and not late["done"] and plan["days_remaining"] == 2
    assert plan["file_contents_opened"] == 0 and "UNMEASURED" in plan["estimate_basis"]
    assert not (tmp_path / "out").exists()
    for needle in FORBIDDEN[:2]:
        assert recorder.touched(needle) == []


def test_resume_by_day_receipt_and_max_days(evidence, tmp_path, monkeypatch):
    out = tmp_path / "out"
    first = tape.run(evidence, out, max_days=1, now=_clock())
    assert [d["utc_day"] for d in first["days"] if d["status"] == "extracted"] == [DAY_LATE.isoformat()]
    assert first["stopped_reason"] == "max_days" and first["days_remaining"] == 1
    late_table = out / "tape" / f"utc_day={DAY_LATE.isoformat()}" / "cf_minutes.parquet"
    sealed_sha = hashlib.sha256(late_table.read_bytes()).hexdigest()
    recorder = Recorder(monkeypatch)
    second = tape.run(evidence, out, max_days=1, now=_clock(STAMP_CLOCK + timedelta(hours=1)))
    assert {d["utc_day"]: d["status"] for d in second["days"]} == {DAY_LATE.isoformat(): "already_sealed",
                                                                  DAY_EARLY.isoformat(): "extracted"}
    assert second["days_remaining"] == 0 and second["stopped_reason"] is None
    assert [e for e in recorder.touched(f"maker_evidence/{DAY_LATE.isoformat()}") if e[0] != "list"] == []
    third = tape.run(evidence, out, now=_clock(STAMP_CLOCK + timedelta(hours=2)))
    assert third["days_extracted"] == 0
    assert hashlib.sha256(late_table.read_bytes()).hexdigest() == sealed_sha
    dry = tape.dry_run(evidence, out)
    assert dry["days_done"] == 2 and dry["days_remaining"] == 0


def test_output_is_create_only_and_interrupted_attempts_are_set_aside(evidence, tmp_path):
    out = tmp_path / "out"
    tape.run(evidence, out, min_date=DAY_LATE, now=_clock())
    day_dir = out / "tape" / f"utc_day={DAY_LATE.isoformat()}"
    original = (day_dir / "cf_fills.parquet").read_bytes()
    os.remove(out / "receipts" / f"{DAY_LATE.isoformat()}.json")      # simulate a run killed before sealing
    tape.run(evidence, out, min_date=DAY_LATE, now=_clock(STAMP_CLOCK + timedelta(hours=1)))
    orphans = sorted(day_dir.glob("cf_fills.parquet.orphan-*"))
    assert len(orphans) == 1 and orphans[0].read_bytes() == original
    # A run receipt that already exists under the same stamp is never overwritten.
    existing = out / "run_receipt_20261017T035501Z.json"
    before = existing.read_bytes()
    with pytest.raises(FileExistsError):
        tape.run(evidence, out, min_date=DAY_LATE, now=_clock())
    assert existing.read_bytes() == before


def test_a_journal_that_differs_from_its_manifest_leaves_the_day_unsealed(evidence, tmp_path):
    segment = next(p for p in (evidence / DAY_EARLY.isoformat()).iterdir())
    journal = segment / "trades.jsonl"
    data = journal.read_bytes()
    assert b"0.40" in data
    journal.write_bytes(data.replace(b"0.40", b"0.41", 1))
    out = tmp_path / "out"
    code = tape.main(["export", "--root", str(evidence), "--out-dir", str(out), "--min-date", DAY_EARLY.isoformat(),
                      "--max-date", DAY_EARLY.isoformat()])
    assert code == 1
    names = os.listdir(out / "receipts")
    assert f"{DAY_EARLY.isoformat()}.json" not in names
    mismatch = json.loads((out / "receipts" / next(n for n in names if ".mismatch-" in n)).read_text())
    assert not mismatch["checks"]["no_segment_or_journal_errors"] and "differs from its manifest" in mismatch["errors"][0]


def test_tables_are_zstd_parquet_with_receipt_hashes(evidence, tmp_path):
    out = tmp_path / "out"
    tape.run(evidence, out, code_commit="e" * 40, now=_clock())
    receipt = json.loads((out / "receipts" / f"{DAY_LATE.isoformat()}.json").read_text())
    assert receipt["code"]["commit"] == "e" * 40 and len(receipt["code"]["module_sha256"]) == 64
    for name, entry in receipt["outputs"].items():
        path = Path(entry["path"])
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]
        meta = pq.ParquetFile(path).metadata
        assert meta.num_rows == entry["rows"] == receipt["rows"]["minutes" if name == "cf_minutes" else "fills"]
        assert meta.row_group(0).column(0).compression == "ZSTD"
    # Four tokens x ten cycles: the first snapshot opens minute 14:01, the last one 14:10.
    assert receipt["rows"]["minutes"] == 40 and receipt["rows"]["fills"] == 1


def test_records_satisfy_the_build2_reader_and_fit_joins(evidence, tmp_path):
    out = tmp_path / "out"
    assert tape.run(evidence, out, now=_clock())["all_match"]
    settlement = tmp_path / "settlement.json"
    settlement.write_text(json.dumps({COND_A: {"p_yes": 1.0, "observed_at_utc": "2026-09-29T05:00:00+00:00"}}),
                          encoding="utf-8")
    for side in ("YES", "NO"):
        target = tmp_path / f"records-{side}.jsonl"
        summary = tape.to_jsonl(out, target, maker_side=side, settlement_path=settlement)
        minutes, fills = build2.read_records(target, purpose="fit")
        build2.check_fit_joins(minutes, fills)
        assert summary["minutes"] == len(minutes) == 26 and summary["fills"] == len(fills)
        assert {m.condition_id for m in minutes} == {COND_A, COND_B}
        assert all(m.context.maker_side == side for m in minutes)
        with pytest.raises(FileExistsError):
            tape.to_jsonl(out, target, maker_side=side)
    minutes, fills = build2.read_records(tmp_path / "records-YES.jsonl", purpose="fit")
    fill = next(f for f in fills if f.event_date == DAY_LATE)
    assert (fill.condition_id, fill.price, fill.size, fill.event_date) == (COND_A, 0.40, 20.0, DAY_LATE)
    assert fill.fill_at_utc == datetime(2026, 9, 28, 14, 1, 20, tzinfo=timezone.utc)
    assert fill.minute_utc == datetime(2026, 9, 28, 14, 1, tzinfo=timezone.utc)
    assert sorted(fill.marks) == ["1m", "5m"] and fill.marks["1m"].mid_yes == pytest.approx(0.42)
    assert fill.settlement_p_yes == 1.0 and fill.context.horizon_days == 0
    assert fill.settlement_observed_at_utc == datetime(2026, 9, 29, 5, tzinfo=timezone.utc)
    # Strictly before the fill: the fill's own A print (size 30) and the B print at the same instant are
    # excluded; only B's print 10 s earlier remains. Counting them would give 30.0 and 2 (and build 2 raises).
    assert fill.context.last_print_size == 0.0 and fill.context.sweep_bands == 1 and fill.context.burst_prints == 0
    assert fill.context.feature_times["prints"] == datetime(2026, 9, 28, 14, 1, 10, tzinfo=timezone.utc)
    assert fill.context.feature_times["book"] < fill.fill_at_utc
    assert fill.context.book_imbalance == pytest.approx((110 - 60) / 170)
    first = min(minutes, key=lambda m: (m.condition_id, m.minute_utc))
    assert first.context.feature_times["book"] <= first.context.at_utc <= first.minute_utc
    assert first.context.minutes_to_close > 0 and first.context.decided_probability is None


def test_strictly_through_rule_does_not_fill_at_the_bid(evidence, tmp_path):
    out = tmp_path / "out"
    tape.run(evidence, out, fill_rule="strictly_through", min_date=DAY_LATE, now=_clock())
    receipt = json.loads((out / "receipts" / f"{DAY_LATE.isoformat()}.json").read_text())
    assert receipt["fill_rule"] == "strictly_through" and receipt["rows"]["fills"] == 0


def test_adapter_refuses_a_table_that_differs_from_its_receipt(evidence, tmp_path):
    out = tmp_path / "out"
    tape.run(evidence, out, min_date=DAY_LATE, now=_clock())
    table = out / "tape" / f"utc_day={DAY_LATE.isoformat()}" / "cf_minutes.parquet"
    table.write_bytes(table.read_bytes() + b"x")
    with pytest.raises(tape.TapeRefused):
        tape.to_jsonl(out, tmp_path / "records.jsonl", maker_side="YES")


def test_context_prints_are_strictly_before_the_instant(evidence, tmp_path):
    out = tmp_path / "out"
    tape.run(evidence, out, min_date=DAY_LATE, now=_clock())
    day_dir = out / "tape" / f"utc_day={DAY_LATE.isoformat()}"
    minutes = pq.read_table(day_dir / "cf_minutes.parquet", partitioning=None).to_pylist()
    fills = pq.read_table(day_dir / "cf_fills.parquet", partitioning=None).to_pylist()
    for row in minutes + fills:
        assert row["ctx_ft_prints"] is None or row["ctx_ft_prints"] < row["ctx_at_utc"]
    for row in fills:
        assert row["ctx_at_utc"] == row["fill_at_utc"] and row["ctx_ft_book"] < row["fill_at_utc"]
    # The 14:02 quote snapshot was taken at 14:01:10, the instant of B's print: that print is not its context.
    snapshot = datetime(2026, 9, 28, 14, 1, 10, tzinfo=timezone.utc)
    at_print = [r for r in minutes if r["quote_snapshot_at_utc"] == snapshot]
    assert at_print and all(r["ctx_sweep_bands"] == 0 and r["ctx_ft_prints"] is None for r in at_print)
    # The exporter's own contract check refuses a context that holds a print at its instant.
    forged = {**{k: tape.to_us(v) if isinstance(v, datetime) else v for k, v in fills[0].items()}}
    forged["ctx_ft_prints"] = forged["fill_at_utc"]
    assert tape.contract_violation("fill", forged) == "prints_not_before_context"


def test_a_backlog_holds_one_fill_rule(evidence, tmp_path):
    out = tmp_path / "out"
    tape.run(evidence, out, min_date=DAY_LATE, now=_clock())
    with pytest.raises(tape.TapeRefused):
        tape.run(evidence, out, fill_rule="strictly_through", now=_clock(STAMP_CLOCK + timedelta(hours=1)))
    assert tape.main(["export", "--root", str(evidence), "--out-dir", str(out), "--fill-rule", "strictly_through"]) == 2
    # The same rule resumes; a separate backlog takes the other rule.
    assert tape.run(evidence, out, now=_clock(STAMP_CLOCK + timedelta(hours=2)))["days_extracted"] == 1
    other = tape.run(evidence, tmp_path / "out-through", fill_rule="strictly_through", now=_clock())
    assert other["fill_rule"] == "strictly_through" and other["days_extracted"] == 2


def test_a_truncated_gzip_journal_leaves_only_its_day_unsealed(evidence, tmp_path):
    segment = next(p for p in (evidence / DAY_LATE.isoformat()).iterdir() if p.name != UNSEALED)
    journal = segment / "trades.jsonl.gz"
    journal.write_bytes(journal.read_bytes()[:-12])
    out = tmp_path / "out"
    receipt = tape.run(evidence, out, now=_clock())
    assert not receipt["all_match"] and receipt["days_extracted"] == 2
    names = os.listdir(out / "receipts")
    assert f"{DAY_EARLY.isoformat()}.json" in names and f"{DAY_LATE.isoformat()}.json" not in names
    mismatch = json.loads((out / "receipts" / next(n for n in names if ".mismatch-" in n)).read_text())
    assert not mismatch["checks"]["no_segment_or_journal_errors"] and mismatch["errors"]


@pytest.mark.parametrize("given, reason", [
    (None, "no_settlement_given"),
    ({}, "no_settlement_given"),
    ({COND_A: {"p_yes": 1.0, "observed_at_utc": "2026-09-28T00:00:00+00:00"}}, "observed_before_fill"),
    ({COND_A: {"p_yes": 1.0, "observed_at_utc": "2026-09-30T01:00:00+00:00"}}, "observed_on_or_after_2026_09_30"),
    ({COND_A: {"p_yes": 1.0, "observed_at_utc": "2026-09-29T05:00:00+00:00"}}, None),
])
def test_adapter_receipt_counts_withheld_settlements(evidence, tmp_path, given, reason):
    out = tmp_path / "out"
    tape.run(evidence, out, min_date=DAY_LATE, now=_clock())
    path = None
    if given is not None:
        path = tmp_path / "settlement.json"
        path.write_text(json.dumps(given), encoding="utf-8")
    target = tmp_path / "records.jsonl"
    summary = tape.to_jsonl(out, target, maker_side="YES", settlement_path=path)
    receipt = json.loads((tmp_path / "records.jsonl.receipt.json").read_text(encoding="utf-8"))
    assert receipt == {k: v for k, v in summary.items() if k != "receipt_path"}
    expected = {name: 0 for name in tape.SETTLEMENT_WITHHELD_REASONS}
    if reason:
        expected[reason] = 1
    assert receipt["fills"] == 1 and receipt["fills_settlement_withheld"] == expected
    assert receipt["fills_with_settlement"] == (0 if reason else 1)
    # The fill is kept (the hazard denominator is unchanged); only its settlement label is withheld,
    # so no 2026-09-30 date reaches build 2.
    minutes, fills = build2.read_records(target, purpose="fit")
    build2.check_fit_joins(minutes, fills)
    assert len(fills) == 1 and (fills[0].settlement_p_yes is None) == bool(reason)
    with pytest.raises(FileExistsError):   # the receipt is create-only, like the output
        os.remove(target)
        tape.to_jsonl(out, target, maker_side="YES", settlement_path=path)
