"""Synthetic-only regression controls for the frozen mission 89a study."""

import csv
import gzip
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from weather.market import fill_toxicity_desk_study as study
from weather.market import fill_toxicity_inputs as source
from weather.market import fill_toxicity_reward_inputs as maker_rewards
from weather.market.maker_evidence_store import EvidenceStore, encoded
from weather.market import fill_toxicity_statistics as stats
from weather.market.fill_toxicity_panels import MinutePanels
from weather.market.fill_toxicity_model import (
    Book, Print, Terms, StudyError, event_window, membership,
    placebo_windows, selected_books, simulate,
)
from weather.market.market_registry import REGISTRY


def ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def book(at=0, *, bid=.48, ask=.52, size=100, tick=.01):
    return Book(at, ((bid, size),), ((ask, size),), tick)


def run(books=None, prints=(), *, terms=None, end=60, rule="conservative", windows=()):
    exposures, fills, diagnostics = [], [], {}
    simulate(books if books is not None else [book()], prints, start=0, end=end,
             terms_at=terms if terms is not None else lambda minute: Terms(0, 1440, 10, 5),
             windows=list(windows), band="b", distance=1.5, rule=rule,
             exposure=lambda *args: exposures.append(args), fill=lambda *args: fills.append(args),
             diagnostics=diagnostics)
    return exposures, fills, diagnostics


def test_import_is_isolated_worktree():
    assert Path(study.__file__).resolve().is_relative_to(Path(__file__).resolve().parents[2])


@pytest.mark.parametrize("bad", [b"\0" * 200, b'{"captured_at_utc":', b'{"bad":"\x01"}'])
def test_undecodable_gzip_records_are_counted_and_make_gaps(tmp_path, bad):
    event = {"folder": str(tmp_path), "market": "nyc", "date": "2026-08-15", "start": 0, "end": 6000}
    path = tmp_path / "order_books.jsonl.gz"
    with gzip.open(path, "wb") as handle:
        for minute in range(100):
            handle.write((bad if minute == 50 else json.dumps({"captured_at_utc": iso(minute * 60)}).encode()) + b"\n")
    defects = source.CaptureDefects(event)
    assert len(list(defects.read(path))) == 99  # Exactly 1% is allowed.
    assert defects.minutes == {49 * 60, 50 * 60}
    assert defects.rows == [{"reason": "undecodable_record", "file": str(path), "line": 51,
        "market": "nyc", "date": "2026-08-15", "gap_start": 49 * 60, "gap_end": 51 * 60}]


def test_undecodable_fraction_refuses_with_file_and_line(tmp_path):
    path = tmp_path / "rows.jsonl"
    path.write_bytes(b'{}\nBROKEN\n')
    defects = source.CaptureDefects({"folder": str(tmp_path), "market": "nyc", "date": "2026-08-15", "start": 0, "end": 6000})
    # Timestamped valid neighbour lets the fraction gate be the refusing gate.
    path.write_bytes(json.dumps({"captured_at_utc": iso(0)}).encode() + b'\nBROKEN\n')
    with pytest.raises(StudyError, match=r"over 1%.*rows.jsonl:2"):
        list(defects.read(path))


def test_undecodable_ledger_always_refuses(tmp_path):
    path = tmp_path / "ledger.jsonl"
    path.write_bytes(b'{}\n' * 200 + b'BROKEN\n')
    with pytest.raises(StudyError, match=r"settlement-ledger row.*ledger.jsonl:201"):
        study.read_settlement(path, "example")


def test_undecodable_shared_file_is_unlocatable(tmp_path):
    folder = tmp_path / "event"
    folder.mkdir()
    path = tmp_path / "shared.jsonl"
    path.write_bytes(b'BROKEN\n')
    defects = source.CaptureDefects({"folder": str(folder), "market": "nyc", "date": "2026-08-15", "start": 0, "end": 6000})
    with pytest.raises(StudyError, match=r"unlocatable record.*shared.jsonl:1"):
        list(defects.read(path))


@pytest.mark.parametrize("bad_index", [0, 99])
def test_boundary_defects_extend_to_event_boundary(tmp_path, bad_index):
    event = {"folder": str(tmp_path), "market": "nyc", "date": "2026-08-15", "start": 0, "end": 6000}
    path = tmp_path / "rows.jsonl"
    with path.open("wb") as handle:
        for minute in range(100):
            handle.write((b'BROKEN' if minute == bad_index else json.dumps({"captured_at_utc": iso(minute * 60)}).encode()) + b'\n')
    defects = source.CaptureDefects(event)
    list(defects.read(path))
    assert defects.rows[0]["gap_start"] == (0 if bad_index == 0 else 5880)
    assert defects.rows[0]["gap_end"] == (60 if bad_index == 0 else 6000)


def test_defect_minutes_union_with_missing_terms_and_withdraw_quotes(tmp_path):
    db = source.open_store(tmp_path / "db.sqlite")
    try:
        db.execute("INSERT INTO bands VALUES ('b','yes',NULL,'x','eq',78,79)")
        db.execute("INSERT INTO terms VALUES ('b',60,1440,10,5,0,'condition_record')")
        bands, counts = study.panel_terms(db, {"start": 0, "end": 180}, [], defect_minutes={0, 60})
        assert counts["missing_term_band_minutes"]["TOTAL"] == 1
        assert counts["capture_defect_band_minutes"]["TOTAL"] == 2
        assert counts["excluded_band_minutes"]["TOTAL"] == 2
        assert counts["excluded_band_minute_fraction"] == pytest.approx(2 / 3)
        exposures, fills, _ = run([book(0), book(60), book(120)], [Print(90, .47, 2)],
                                  terms=bands[0]["terms"].get, end=180)
        assert fills == []
        assert sum(row[2] for row in exposures) == 40
    finally:
        db.close()


def test_corrupt_book_end_to_end_excludes_exposure_and_reports_record(tmp_path):
    event = synthetic_event(tmp_path)
    path = Path(event["book"])
    lines = path.read_bytes().splitlines(keepends=True)
    lines[740] = b'\0\0\0\n'
    path.write_bytes(b''.join(lines))
    report = study.run_study([event], tmp_path / "output", replicates=2)
    note = report["events"][0]
    assert note["undecodable_records"] == 1
    assert note["record_exclusions"][0]["line"] == 741
    assert note["tape_gap_minutes"] == 2
    assert note["book_minutes"] == 1438
    assert note["capture_defect_band_minutes"]["TOTAL"] == 2
    assert report["R"]["d1.5_conservative/midrange"]["sufficient_statistics"]["total"]["filled_shares"] == 0


def test_capture_gap_union_counts_overlap_once_and_applies_five_percent(tmp_path):
    event = synthetic_event(tmp_path)
    defects = source.CaptureDefects(event)
    a = event["start"]
    defects.add(event["book"], [2, 3], {"captured_at_utc": iso(a)}, {"captured_at_utc": iso(a + 73 * 60)})
    gaps = Path(event["folder"]) / "gaps.jsonl"
    write_rows(gaps, [{"gap_id": "overlap", "disconnected_at_utc": iso(a), "reconnected_at_utc": iso(a + 60)}])
    quality = source.coverage(event["summary"], [gaps], event["status"], a, event["end"], defects=defects)
    assert quality["tape_gap_minutes"] == 73
    assert quality["book_minutes"] == 1440 - 73
    assert "tape_gap_minutes_above_5_percent" in quality["exclusions"]


def test_prepass_defects_survive_early_event_exclusion(tmp_path):
    event = synthetic_event(tmp_path)
    path = Path(event["weather"][0])
    rows = path.read_bytes().splitlines(keepends=True)
    path.write_bytes(b''.join(rows * 5) + b'BROKEN\n')
    event["summary"] = None
    report = study.run_study([event], tmp_path / "output", replicates=2)
    assert report["events"][0]["record_exclusions"][0]["line"] == 121


@pytest.mark.parametrize("price,rule,filled", [(.47, "conservative", True), (.48, "conservative", False),
    (.48, "optimistic", True), (.47, "optimistic", True), (.49, "optimistic", False),
    (.53, "conservative", True), (.52, "optimistic", True), (.52, "conservative", False)])
def test_snapped_price_fill_rules(price, rule, filled):
    _, fills, _ = run(prints=[Print(15, price, 3)], rule=rule)
    assert bool(fills) == filled
    if fills:
        assert fills[0][1] == 3
        assert fills[0][2] == (.48 if price < .5 else .52)


def test_partial_fills_remove_exposure_and_replacement_restores_twenty():
    exposures, fills, _ = run([book(0), book(60)],
        [Print(15, .47, 8), Print(30, .47, 50), Print(45, .47, 3), Print(75, .47, 5)], end=120)
    assert [fill[1] for fill in fills] == [8, 12, 5]
    assert sum(row[2] for row in exposures) == pytest.approx(64.25)


def test_no_repricing_between_selected_samples():
    _, fills, _ = run([book(0), book(20, bid=.38, ask=.42), book(60, bid=.38, ask=.42)],
                     [Print(30, .47, 2), Print(90, .47, 2)], end=120)
    assert [fill[2] for fill in fills] == [.48, .42]
    assert [fill[3] for fill in fills] == ["bought", "sold"]


def test_first_in_minute_then_thirty_second_spacing():
    assert [row.at for row in selected_books([book(50), book(61), book(95), book(121)])] == [50, 121]


def test_missing_samples_withdraw_at_five_minutes():
    exposures, fills, _ = run([book(0)], [Print(300, .47, 1)], end=420)
    assert sum(row[2] for row in exposures) == 200
    assert fills == []


def test_missing_terms_withdraw_at_minute_start():
    exposures, fills, _ = run([book(0)], [Print(60, .47, 1)], end=120,
                             terms=lambda minute: Terms(0, 100, 10, 5) if minute < 60 else None)
    assert sum(row[2] for row in exposures) == 40
    assert fills == []


@pytest.mark.parametrize("minimum,rate,spread", [(100, 1440, 5), (10, 0, 5), (10, 1440, 1)])
def test_ineligible_minutes_have_zero_reward_without_becoming_missing(minimum, rate, spread):
    exposures, fills, _ = run(prints=[Print(30, .47, 3)], terms=lambda _: Terms(0, rate, minimum, spread))
    assert sum(row[3] for row in exposures) == 0
    assert len(fills) == 1


def test_partial_fill_below_minimum_zeroes_that_leg_score():
    exposures, _, _ = run(prints=[Print(30, .47, 11)])
    assert exposures[1][3] < exposures[0][3]


@pytest.mark.parametrize("kind,pre,post", [("E1", 3, 10), ("E2", 10, 15), ("E3", 15, 15), ("E4", 5, 30), ("E5", 10, 25)])
def test_frozen_windows_are_half_open(kind, pre, post):
    window = event_window(kind, 3600)
    assert (window.start, window.end) == (3600 - pre * 60, 3600 + post * 60)
    assert kind in membership([window], window.start, "b")
    assert kind not in membership([window], window.end, "b")


def test_placebo_same_hour_duration_and_overlap_drop():
    utc = ZoneInfo("UTC")
    windows, dropped = placebo_windows([event_window("E1", 0)], utc)
    assert dropped == 0
    assert (windows[0].start, windows[0].end) == (1200, 1980)
    windows, dropped = placebo_windows([event_window("E1", 0), event_window("E2", 1500)], utc)
    assert windows == [] and dropped == 2


def test_e3_is_band_specific():
    w = event_window("E3", 60, band="a")
    assert "E3" in membership([w], 60, "a")
    assert "E3" not in membership([w], 60, "b")


def test_missing_terms_threshold_uses_band_minutes(tmp_path):
    db = source.open_store(tmp_path / "db.sqlite")
    try:
        for band in ("a", "b"):
            db.execute("INSERT INTO bands VALUES (?,?,?,?,?,?,?)", (band, band, None, "x", "eq", 78, 79))
        db.execute("INSERT INTO terms VALUES ('a',0,10,20,5,0,'condition_record')")
        db.execute("INSERT INTO terms VALUES ('b',60,10,20,5,0,'condition_record')")
        bands, counts = study.panel_terms(db, {"start": 0, "end": 120}, [])
        assert len(bands) == 2
        assert counts["expected_band_minutes"] == 4
        assert counts["missing_term_band_minutes"]["TOTAL"] == 1
        assert counts["missing_term_fraction"] == .25
    finally:
        db.close()


def test_reward_freshness_and_record_precedence(tmp_path):
    db = source.open_store(tmp_path / "db.sqlite")
    try:
        db.execute("INSERT INTO terms VALUES ('a',0,10,20,5,0,'condition_record')")
        db.execute("INSERT INTO terms VALUES ('a',60,999,20,5,1,'embedded_config')")
        assert source.terms_at(db, "a", 60).rate == 10
        assert source.terms_at(db, "a", 3600) is not None
        assert source.terms_at(db, "a", 3660) is None
        assert source.terms_at(db, "a", -60) is None
    finally:
        db.close()


def synthetic_rows(n=10):
    rows = []
    for day in range(n):
        total, inside, outside = stats.zero(), stats.zero(), stats.zero()
        total.update(exposure=100, loss=20, net_loss=20, reward_many=10, reward_single=12, filled_shares=40, band_days=1)
        inside.update(exposure=20, loss=15, net_loss=15, reward_many=2, reward_single=3, filled_shares=20)
        outside.update(exposure=80, loss=5, reward_many=8, reward_single=9, filled_shares=20)
        rows.append(((str(day), "nyc"), total, inside, outside))
    return rows


def test_estimands_and_fixed_seed_bootstrap():
    result = stats.summarize(synthetic_rows(), "control", replicates=50)
    assert result == stats.summarize(synthetic_rows(), "control", replicates=50)
    assert result["point"]["CR"] == 12
    assert stats.summarize(synthetic_rows(), "R", replicates=50, reward_only=True)["point"]["R"] == .25
    assert result["point"]["net_pull_per_band_day"] == 13
    assert stats.decision(result)["verdict"] == "PULL_SUPPORTED"


def test_under_ten_dates_forces_inconclusive():
    result = stats.summarize(synthetic_rows(9), "control", replicates=50)
    assert result["interval_flag"] == "UNDERPOWERED"
    assert stats.decision(result) == {"verdict": "INCONCLUSIVE", "reason": "UNDERPOWERED"}


def test_crossed_sensitivity_preserves_market_effects_with_identical_dates():
    rows = synthetic_rows()
    for (day, market), total, inside, outside in synthetic_rows():
        inside["loss"] = 3
        rows.append(((day, "other"), total, inside, outside))
    date_result = stats.summarize(rows, "date-control", replicates=100)
    crossed = stats.summarize(rows, "crossed-control", replicates=100, crossed=True)
    assert date_result["interval_90"]["CR"] == pytest.approx([7.2, 7.2])
    assert crossed["interval_90"]["CR"] == pytest.approx([2.4, 12])
    assert crossed["date_clusters"] == 10 and crossed["market_clusters"] == 2
    assert crossed["cluster"] == "crossed_date_market"


def test_settlement_authority_and_flagged_fallback():
    band = {"label": "78-79 F", "kind": "eq", "lo": 78, "hi": 79}
    assert study.settlement_mark({"polymarket_winning_band": "78-79 F", "settlement_bucket": 90}, band) == (1, "polymarket_winning_band")
    assert study.settlement_mark({"settlement_bucket": 79}, band) == (1, "WU_FALLBACK")
    assert study.settlement_mark(None, band)[0] is None
    assert study.settlement_mark({"polymarket_winning_band": "78-79\u00b0F"}, band)[0] == 1


def test_settlement_revision_order_is_canonical(tmp_path):
    path = tmp_path / "ledger.jsonl"
    write_rows(path, [{"event_slug": "synthetic", "revision_number": 3, "settlement_bucket": 79},
                     {"event_slug": "synthetic", "revision_number": 2, "settlement_bucket": 80}])
    assert study.read_settlement(path, "synthetic")["settlement_bucket"] == 79


def test_dry_run_does_not_open_tape(tmp_path, monkeypatch, capsys):
    plan = [{"book": str(tmp_path / "book.jsonl"), "summary": None, "status": None, "ledger": None,
             "trades": [], "gaps": [], "weather": [], "rewards": [], "triggers": []}]
    (tmp_path / "book.jsonl").write_text("not json\n")
    monkeypatch.setattr(study, "input_plan", lambda *a, **k: plan)
    monkeypatch.setattr(source, "json_lines", lambda *a: pytest.fail("dry-run read content"))
    assert study.main(["--output-dir", str(tmp_path / "output"), "--dry-run"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["inputs"][0]["bytes"] == (tmp_path / "book.jsonl").stat().st_size
    assert not (tmp_path / "output").exists()


def test_output_under_data_refused(tmp_path):
    with pytest.raises(study.base.MarkoutError):
        study.run_study([], tmp_path / "data" / "report")


def test_cli_inventory_names_all_twelve_markets_without_reading_content(tmp_path, capsys):
    event = synthetic_event(tmp_path)
    Path(event["book"]).write_text("deliberately invalid tape content\n")
    assert study.main(["--snapshots-root", str(tmp_path), "--settlement-root", str(tmp_path / "settlements"),
        "--max-dates", "1", "--output-dir", str(tmp_path / "output"), "--dry-run"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert len(result["events"]) == len(REGISTRY) == 12
    selected = next(row for row in result["events"] if row["market"] == "nyc")
    assert Path(selected["book"]) == Path(event["book"])
    assert not (tmp_path / "output").exists()


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def iso(at):
    return datetime.fromtimestamp(at, timezone.utc).isoformat()


MAKER_CONDITION = "0x" + "a" * 64


def synthetic_maker_rewards(root, slug, times, *, sealed=True, rates=None, query=""):
    """88a's real writer, documented production response shape, invented values."""
    clock = [datetime.fromtimestamp(times[0], timezone.utc)]
    store = EvidenceStore(root, clock=lambda: clock[0])
    body = encoded({"count": 1, "limit": 100, "next_cursor": "LTE=", "data": [{
        "condition_id": MAKER_CONDITION, "market_slug": "synthetic-78-79", "event_slug": slug,
        "tokens": [{"token_id": "1", "outcome": "Yes", "price": .5},
                   {"token_id": "2", "outcome": "No", "price": .5}],
        "rewards_config": [{"asset_address": "0x" + "b" * 40, "start_date": "2026-08-15",
                            "end_date": "2026-08-16", "id": "synthetic", "rate_per_day": 1440,
                            "total_rewards": 1440, "total_days": 1}],
        "rewards_max_spread": 4.5, "rewards_min_size": 100}]})
    for index, at in enumerate(times):
        clock[0] = datetime.fromtimestamp(at, timezone.utc)
        if rates is not None:
            value = json.loads(body)
            value["data"][0]["rewards_config"][0]["rate_per_day"] = rates[index]
            body = encoded(value)
        store.record("rewards", body, change_key="rewards:" + MAKER_CONDITION,
                     metadata={"http_status": 200, "latency_seconds": .01,
                               "request_sha256": "c" * 64,
                               "url": "https://clob.polymarket.com/rewards/markets/" + MAKER_CONDITION + query})
    if sealed:
        store.seal()
    # Use gzip even for an unsealed test segment to prove the seal is required.
    for path in root.glob("*/*/*"):
        if path.suffix in (".jsonl", ".json"):
            path.with_suffix(path.suffix + ".gz").write_bytes(gzip.compress(path.read_bytes()))
    return sorted(root.glob("*/*/reward-*.jsonl.gz"))


def test_maker_reward_unwrap_and_unchanged_minute_uses_new_capture(tmp_path):
    start = ts("2026-08-15T04:00:00Z")
    paths = synthetic_maker_rewards(tmp_path / "maker", "synthetic", [start, start + 60])
    raw = list(source.json_lines(paths[0]))
    assert raw[0]["body_stored"] is True
    assert raw[1]["body_stored"] is False
    assert raw[1]["payload_ref"] == {"file": paths[0].name.removesuffix(".gz"), "offset": 0}
    db = source.open_store(tmp_path / "terms.sqlite")
    try:
        maker_rewards.stage_rewards(db, paths, "synthetic", start, start + 7200)
        assert db.execute("SELECT COUNT(*) FROM terms").fetchone()[0] == 2
        terms = source.terms_at(db, MAKER_CONDITION, start + 3660)
        assert terms.captured == start + 60  # Exactly 60 minutes old remains fresh.
        assert (terms.rate, terms.minimum, terms.spread) == (1440, 100, 4.5)
        assert source.terms_at(db, MAKER_CONDITION, start - 60) is None
        assert source.terms_at(db, MAKER_CONDITION, start + 3720) is None
    finally:
        db.close()


def test_maker_reward_planning_is_metadata_only_and_ignores_unsealed(tmp_path, monkeypatch):
    start = ts("2026-08-15T04:00:00Z")
    root = tmp_path / "maker"
    paths = synthetic_maker_rewards(root, "synthetic", [start - 3600, start])
    synthetic_maker_rewards(tmp_path / "active", "synthetic", [start], sealed=False)
    # A completed segment from an irrelevant hour must not be included.
    synthetic_maker_rewards(root, "synthetic", [start + 7200])
    monkeypatch.setattr(gzip, "open", lambda *a, **k: pytest.fail("planning opened content"))
    assert maker_rewards.plan_rewards(root, start, start + 3600) == list(map(str, paths))
    assert maker_rewards.plan_rewards(tmp_path / "active", start, start + 3600) == []
    plan = study.input_plan(tmp_path / "snapshots", tmp_path / "settlements", max_dates=1,
                            maker_evidence_root=root)
    event = next(row for row in plan if row["market"] == "nyc")
    assert set(map(str, paths)) <= set(event["maker_rewards"])
    inventory = {row["path"] for row in study.inventory([event])}
    assert str(paths[0].resolve()) in inventory
    assert str((paths[0].parent / "manifest.json.gz").resolve()) in inventory


def test_maker_reward_nonzero_uncompressed_reference_and_pagination(tmp_path):
    start = ts("2026-08-15T04:00:00Z")
    path, = synthetic_maker_rewards(tmp_path / "maker", "synthetic", [start, start + 60, start + 120],
                                    rates=[1440, 720, 720], query="?next_cursor=c3ludGhldGlj")
    raw = list(source.json_lines(path))
    assert raw[2]["payload_ref"]["offset"] == raw[1]["offset"] > 0
    rows = list(maker_rewards.reward_rows(path, "synthetic", start, start + 3600))
    assert [row["rewards_config"][0]["rate_per_day"] for row in rows] == [1440, 720, 720]
    assert [source.epoch(row["captured_at_utc"]) for row in rows] == [start, start + 60, start + 120]


def test_maker_rewards_reject_direct_unsealed_input(tmp_path):
    start = ts("2026-08-15T04:00:00Z")
    paths = synthetic_maker_rewards(tmp_path / "maker", "synthetic", [start], sealed=False)
    with pytest.raises(StudyError, match="unsealed"):
        list(maker_rewards.reward_rows(paths[0], "synthetic", start, start + 3600))


def test_maker_rewards_do_not_mix_events(tmp_path):
    start = ts("2026-08-15T04:00:00Z")
    path, = synthetic_maker_rewards(tmp_path / "maker", "other-event", [start])
    assert list(maker_rewards.reward_rows(path, "synthetic", start, start + 3600)) == []


@pytest.mark.parametrize("mutation,reason", [
    (lambda rows: rows[1]["payload_ref"].update(file="../escape.jsonl"), "payload reference"),
    (lambda rows: rows[1]["payload_ref"].update(offset=1), "record|offset"),
    (lambda rows: rows[1].update(content_sha256="0" * 64), "reference mismatch"),
    (lambda rows: rows[0].update(body_utf8="broken"), "undecodable"),
    (lambda rows: rows[0].update(url="https://clob.polymarket.com/rewards/markets/0x" + "d" * 64), "condition mismatch"),
])
def test_maker_reward_bad_reference_or_body_refuses(tmp_path, mutation, reason):
    start = ts("2026-08-15T04:00:00Z")
    path, = synthetic_maker_rewards(tmp_path / "maker", "synthetic", [start, start + 60])
    rows = list(source.json_lines(path))
    mutation(rows)
    # Repair offsets and seal after mutation to exercise the payload/shape gate.
    raw = b""
    for row in rows:
        row["offset"] = len(raw)
        raw += encoded(row) + b"\n"
    path.write_bytes(gzip.compress(raw))
    import hashlib
    manifest = path.parent / "manifest.json.gz"
    info = json.loads(gzip.decompress(manifest.read_bytes()))
    info["files"][path.name.removesuffix(".gz")].update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    manifest.write_bytes(gzip.compress(encoded(info)))
    with pytest.raises(StudyError, match=reason):
        list(maker_rewards.reward_rows(path, "synthetic", start, start + 3600))


def test_maker_reward_sealed_hash_and_decompressed_line_bound(tmp_path, monkeypatch):
    start = ts("2026-08-15T04:00:00Z")
    path, = synthetic_maker_rewards(tmp_path / "maker", "synthetic", [start])
    manifest = path.parent / "manifest.json.gz"
    info = json.loads(gzip.decompress(manifest.read_bytes()))
    info["files"][path.name.removesuffix(".gz")]["sha256"] = "0" * 64
    manifest.write_bytes(gzip.compress(encoded(info)))
    with pytest.raises(StudyError, match="sealed file integrity"):
        list(maker_rewards.reward_rows(path, "synthetic", start, start + 3600))
    monkeypatch.setattr(maker_rewards, "MAX_LINE_BYTES", 100)
    with pytest.raises(StudyError, match="oversized"):
        list(maker_rewards.reward_rows(path, "synthetic", start, start + 3600))


def test_maker_reward_only_event_end_to_end(tmp_path):
    event = synthetic_event(tmp_path)
    event["rewards"] = []
    path = Path(event["book"])
    path.write_text(path.read_text().replace('"b"', json.dumps(MAKER_CONDITION)), encoding="utf-8")
    event["maker_rewards"] = list(map(str, synthetic_maker_rewards(tmp_path / "maker", event["slug"],
        [event["start"] + minute * 60 for minute in range(1440)])))
    result = study.run_study([event], tmp_path / "output", replicates=2)
    assert result["events"][0]["exclusions"] == []
    assert result["events"][0]["missing_term_fraction"] == 0
    assert result["events"][0]["bands"][0]["condition"] == MAKER_CONDITION


def synthetic_event(tmp_path):
    folder = tmp_path / "highest-temperature-in-nyc-on-august-15-2026"
    folder.mkdir()
    start = ts("2026-08-15T04:00:00Z")
    end = start + 86400
    event = {"date": "2026-08-15", "market": "nyc", "slug": folder.name, "folder": str(folder),
        "start": start, "end": end, "book": str(folder / "order_books.jsonl"),
        "summary": str(folder / "order_books_summary.csv"), "trades": [str(folder / "execution_tape" / "trades-00000.jsonl")],
        "gaps": [], "status": str(folder / "status.json"), "weather": [str(folder / "replay_inputs.jsonl")],
        "rewards": [str(folder / "rewards.jsonl")], "triggers": [str(folder / "observation_triggers.jsonl")],
        "ledger": str(folder / "ledger.jsonl")}
    def books():
        for minute in range(1440):
            at = start + 60 * minute
            mid = .5 if minute < 750 else .4
            yield {"captured_at_utc": iso(at), "clob_token_id": "yes", "token": {"condition_id": "b",
                "outcome": "Yes", "range_label": "78-79 F", "bin_kind": "eq", "bin_value": 78, "bin_value_hi": 79},
                "book": {"market": "b", "asset_id": "yes", "tick_size": ".01",
                    "bids": [{"price": mid - .02, "size": 100}], "asks": [{"price": mid + .02, "size": 100}]}}
    write_rows(Path(event["book"]), books())
    with Path(event["summary"]).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["captured_at_utc"])
        writer.writeheader()
        writer.writerows({"captured_at_utc": iso(start + 60 * minute)} for minute in range(1440))
    Path(event["status"]).write_text(json.dumps({"target_date": event["date"], "event_slug": event["slug"], "open_gap": None}))
    write_rows(Path(event["rewards"][0]), ({"condition_id": "b", "captured_at_utc": iso(start + hour * 3600),
        "rate": 1440, "min_size": 20, "max_spread": 5} for hour in range(24)))
    write_rows(Path(event["weather"][0]), ({"captured_at_utc": iso(start + hour * 3600 + 54 * 60),
        "sources": {"metar": {"data": {"rows": [{"report_time": iso(start + hour * 3600 + 53 * 60),
        "temp_native": 78 if hour < 12 else 80, "raw": "METAR KLGA"}]}},
        "nbm_probabilistic": {"data": {"provider_update_time": iso(start + 3 * 3600)}}}}
        for hour in range(24)))
    write_rows(Path(event["triggers"][0]), [{"trigger_context": {"triggers": [{"reason": "metar_temp_bucket_crossed",
        "market_id": "nyc", "observed_at": iso(start + 12 * 3600 + 53 * 60),
        "current_captured_at_utc": iso(start + 12 * 3600 + 54 * 60)}]}}])
    write_rows(Path(event["trades"][0]), [{"asset_id": "yes", "price": ".47", "size": "3", "side": "SELL",
        "timestamp": str(int((start + 740 * 60 + 10) * 1000)), "transaction_hash": "synthetic-1"}])
    write_rows(Path(event["ledger"]), [{"event_slug": folder.name, "polymarket_winning_band": "80-81 F", "settlement_bucket": 78}])
    return event


def test_native_synthetic_event_end_to_end(tmp_path):
    event = synthetic_event(tmp_path)
    result = study.run_study([event], tmp_path / "output", replicates=10)
    assert result["decision"] == {"verdict": "INCONCLUSIVE", "reason": "UNDERPOWERED"}
    assert result["events"][0]["exclusions"] == []
    assert result["events"][0]["routine_metar_minute"] == 53
    assert result["events"][0]["missing_term_fraction"] == 0
    cell = result["results"][result["primary"]]
    assert cell["sufficient_statistics"]["total"]["filled_shares"] == 3
    assert cell["sufficient_statistics"]["total"]["loss"] == pytest.approx(.24)
    assert result["events"][0]["bands"][0]["settlement_source"] == "polymarket_winning_band"
    with gzip.open(tmp_path / "output" / "intermediates.jsonl.gz", "rt") as handle:
        windows = [row for line in handle if (row := json.loads(line))["type"] == "window"]
    e3 = [row for row in windows if row["kind"] == "E3"]
    assert len(e3) == 1
    assert e3[0]["observed"] == event["start"] + 12 * 3600 + 53 * 60
    assert any(row["kind"] == "E2_DETECTED" for row in windows)
    assert {row["kind"] for row in windows} >= {"E1", "E2", "E3", "E4", "E5"}


def test_e3_hourly_filter_speci_and_open_top(tmp_path):
    db = source.open_store(tmp_path / "db.sqlite")
    try:
        db.execute("INSERT INTO bands VALUES ('b','yes',NULL,'x','eq',78,79)")
        db.execute("INSERT INTO bands VALUES ('top','yes-top',NULL,'top','gte',80,80)")
        for row in [(10 * 60, 11 * 60, 90, 0), (53 * 60, 54 * 60, 78, 1), (113 * 60, 114 * 60, 80, 1)]:
            db.execute("INSERT INTO observations VALUES (?,?,?,?)", row)
        windows, _ = source.windows_for_event(db, REGISTRY["nyc"], 0, 86400)
        e3 = [row for row in windows if row.kind == "E3"]
        assert [(row.band, row.observed) for row in e3] == [("b", 113 * 60)]
    finally:
        db.close()


def test_toronto_uses_wu_rows_unfiltered(tmp_path):
    path = tmp_path / "weather.jsonl"
    write_rows(path, [{"captured_at_utc": iso(1200), "sources": {"wu_history": {"data": {"rows": [
        {"datetime": iso(900), "temp_native": 25.5}]}}}}])
    db = source.open_store(tmp_path / "db.sqlite")
    try:
        source.stage_weather(db, [path], [], REGISTRY["toronto"], 0, 86400)
        db.execute("INSERT INTO bands VALUES ('b','yes',NULL,'x','eq',25,25)")
        windows, _ = source.windows_for_event(db, REGISTRY["toronto"], 0, 86400)
        assert [(w.kind, w.observed) for w in windows if w.kind in ("E1", "E3")] == [("E1", 900), ("E3", 900)]
    finally:
        db.close()


def test_gap_and_coverage_thresholds(tmp_path):
    event = synthetic_event(tmp_path)
    gaps = tmp_path / "gaps.jsonl"
    write_rows(gaps, [{"gap_id": "g", "gap_state": "CLOSED", "disconnected_at_utc": iso(event["start"]),
        "reconnected_at_utc": iso(event["start"] + 73 * 60)}])
    result = source.coverage(event["summary"], [gaps], None, event["start"], event["end"])
    assert "tape_gap_minutes_above_5_percent" in result["exclusions"]
    result = source.coverage(event["summary"], [], None, event["start"], event["end"])
    assert result["exclusions"] == ["no_execution_gap_or_status_record"]


def test_coverage_reads_summary_rows_with_wide_cells(tmp_path):
    event = synthetic_event(tmp_path)
    with Path(event["summary"]).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["captured_at_utc", "book_json"])
        writer.writeheader()
        writer.writerows({"captured_at_utc": iso(event["start"] + 60 * minute), "book_json": "x" * 200_000 if minute == 0 else ""} for minute in range(1440))
    result = source.coverage(event["summary"], [], None, event["start"], event["end"])
    assert result["exclusions"] == ["no_execution_gap_or_status_record"]


def test_disk_sorted_duplicate_collapse_and_complement(tmp_path):
    path = tmp_path / "trades.jsonl"
    rows = [{"asset_id": "y", "timestamp": "3000", "price": ".4", "size": "2", "side": "SELL", "transaction_hash": "x"},
            {"asset_id": "n", "timestamp": "1000", "price": ".6", "size": "1", "side": "BUY", "transaction_hash": "z"}]
    write_rows(path, [rows[0], rows[1], rows[0]])
    db = source.open_store(tmp_path / "db.sqlite")
    try:
        counters = {}
        source.stage_trades(db, [path], 0, 10, counters)
        assert counters["duplicate_identities"] == 1
        values = list(source.iter_prints(db, "y", "n"))
        assert [row.at for row in values] == [1, 3]
        assert [row.price for row in values] == [.4, .4]
    finally:
        db.close()


def test_large_synthetic_date_uses_bounded_memory(tmp_path):
    import tracemalloc
    path = tmp_path / "large.jsonl"
    write_rows(path, ({"asset_id": "y", "timestamp": str(1_000 + index), "price": ".4", "size": "1", "side": "SELL",
                       "transaction_hash": str(index)} for index in range(100_000)))
    db = source.open_store(tmp_path / "db.sqlite")
    tracemalloc.start()
    try:
        source.stage_trades(db, [path], 0, 86400, {})
        assert sum(1 for _ in source.iter_prints(db, "y")) == 100_000
        peak = tracemalloc.get_traced_memory()[1]
        assert peak < 8 * 1024 * 1024
        print(f"synthetic_100000_trades_peak_python_bytes={peak}")
    finally:
        tracemalloc.stop()
        db.close()


def test_horizon_panels_remove_whole_leg_but_net_removes_both():
    from collections import defaultdict
    cells, audit = defaultdict(stats.zero), []
    panel = MinutePanels(midpoint=lambda at, adjusted: None if at == 1810 else .6,
        payoff=0, end=60, emit=lambda p, a, h, g, v: stats.add(cells[(h, g)], v) if not a else None,
        audit=audit.append)
    panel.exposure(0, 10, 40 / 6, .1, .2, {"E1"}, "midrange", (20, 20))
    panel.fill(10, 3, .48, "bought", {"E1"}, "midrange")
    panel.exposure(10, 20, 37 / 6, .1, .2, {"E1"}, "midrange", (17, 20))
    panel.fill(20, 2, .52, "sold", {"E1"}, "midrange")
    panel.exposure(20, 40, 35 / 3, .2, .4, {"E1"}, "midrange", (17, 18))
    panel.fill(40, 1, .48, "bought", {"E1"}, "midrange")
    panel.exposure(40, 60, 34 / 3, .2, .4, {"E1"}, "midrange", (16, 18))
    panel.flush()
    assert cells[("30m", "TOTAL")]["fills"] == 1
    assert cells[("30m", "TOTAL")]["filled_shares"] == 2
    assert cells[("30m", "TOTAL")]["exposure"] == pytest.approx(20 / 3 + 18 * 2 / 3)
    assert cells[("30m", "TOTAL")]["loss"] == pytest.approx(.16)
    assert cells[("30m", "TOTAL")]["net_loss"] == 0
    assert cells[("30m", "TOTAL")]["reward_many"] == 0
    assert cells[("1m", "TOTAL")]["fills"] == cells[("5m", "TOTAL")]["fills"] == 3
    assert cells[("settlement", "TOTAL")]["filled_shares"] == 6
    removed = next(row for row in audit if row["type"] == "removed_leg_minutes" and row["midpoint"] == "book_mid")
    assert removed["leg_minutes_by_group"]["TOTAL"] == 1
    assert removed["fills_by_group"]["TOTAL"] == 2
    assert any(row["type"] == "removed_quote_minutes" and row["quote_minutes_by_group"]["E1"] == 1 for row in audit)


@pytest.mark.parametrize("missing", [1800, 1860])
def test_both_horizon_boundaries_required(missing):
    cells = []
    panel = MinutePanels(midpoint=lambda at, adjusted: None if at == missing else .5,
        payoff=None, end=60, emit=lambda *args: cells.append(args), audit=lambda row: None)
    panel.exposure(0, 60, 40, 1, 2, {"E1"}, "midrange", (20, 20))
    panel.flush()
    assert not any(row[2] == "30m" for row in cells)
    assert any(row[2] == "1m" and row[4]["exposure"] == 20 for row in cells)


def test_joint_reward_is_preserved_exactly_when_both_legs_survive():
    cells = []
    panel = MinutePanels(midpoint=lambda *args: .4, payoff=1, end=60,
        emit=lambda *args: cells.append(args), audit=lambda row: None)
    panel.exposure(0, 60, 40, .123, .456, {"E1"}, "midrange", (20, 20))
    panel.flush()
    joint = [row[4] for row in cells if row[1:4] == (False, "30m", "TOTAL") and row[4]["reward_many"]]
    assert len(joint) == 1
    assert joint[0]["reward_many"] == .123
    assert joint[0]["reward_single"] == .456


def test_R_uses_full_panel_when_thirty_minute_leg_is_missing(tmp_path, monkeypatch):
    db = source.open_store(tmp_path / "db.sqlite")
    try:
        monkeypatch.setattr(source, "iter_books", lambda *args: iter([book(0)]))
        monkeypatch.setattr(source, "iter_prints", lambda *args: iter([Print(10, .47, 3), Print(20, .53, 2)]))
        monkeypatch.setattr(source, "midpoint", lambda db, token, at, **kwargs: None if at == 1810 else .6)
        event = {"start": 0, "end": 60, "slug": "synthetic", "date": "2026-08-15", "market": "nyc"}
        band = {"condition": "b", "token": "yes", "no_token": None, "label": "78-79 F", "kind": "eq",
                "lo": 78, "hi": 79, "terms": {0: Terms(0, 1440, 10, 5)}}
        cells, _ = study.process_band(db, event, band, [], {"settlement_bucket": 78}, io.StringIO())
        prefix = ("d1.5_conservative", "midrange", "book_mid")
        full = cells[(*prefix, "R", "TOTAL")]
        thirty = cells[(*prefix, "30m", "TOTAL")]
        assert full["filled_shares"] == 5
        assert full["reward_many"] > 0
        assert thirty["filled_shares"] == 2
        assert thirty["reward_many"] == thirty["net_loss"] == 0
    finally:
        db.close()


@pytest.mark.parametrize("cr,net,verdict", [([2, 3], [.001, 1], "PULL_SUPPORTED"),
    ([2, 3], [0, 1], "INCONCLUSIVE"), ([1, 1.5], [-2, 1], "PULL_NOT_THE_LEVER"),
    ([1, 1.50001], [-2, 1], "INCONCLUSIVE")])
def test_exact_decision_boundaries(cr, net, verdict):
    result = {"date_clusters": 10, "interval_90": {"CR": cr, "net_pull_per_band_day": net}}
    assert stats.decision(result)["verdict"] == verdict


def test_kill_selects_best_point_of_seven_and_checks_its_upper_bound():
    rows = {name: {"point": {"net_pull_per_band_day": index}, "date_clusters": 10,
        "interval_90": {"net_after_pull_per_band_day": [-2, -1]}} for index, name in enumerate(study.WINDOW_SETS)}
    result = stats.kill_decision(rows)
    assert result["selected_set"] == "ALL" and result["verdict"] == "KILL"
    rows["ALL"]["interval_90"]["net_after_pull_per_band_day"][1] = 0
    assert stats.kill_decision(rows)["verdict"] == "INCONCLUSIVE"


def test_latency_median_interval_threshold_and_underpowered():
    result = stats.latency_summary({str(day): [.70] for day in range(10)}, "latency", replicates=25)
    assert result["reactive_pull_useless"] and result["interval_90"] == [.70, .70]
    assert not stats.latency_summary({"only": [1.0]}, "latency", replicates=25)["reactive_pull_useless"]


def test_zero_terms_are_usable_and_captured_nulls_still_define_panel():
    assert Terms(0, 0, 0, 0).usable(0)
    rows = list(source.term_rows({"captured_at_utc": iso(0), "condition_id": "b", "rewards_min_size": None}))
    assert len(rows) == 1
    assert rows[0][2:5] == (None, None, None)


def test_e4_cycle_identity_uses_issue_time_when_fetch_is_later(tmp_path):
    path = tmp_path / "weather.jsonl"
    write_rows(path, [{"captured_at_utc": iso(8 * 3600), "sources": {"nbm_probabilistic_tmax": {
        "fetched_at": iso(7 * 3600 + 65 * 60), "data": {"issued_at": iso(7 * 3600)}}}}])
    db = source.open_store(tmp_path / "db.sqlite")
    try:
        source.stage_weather(db, [path], [], REGISTRY["nyc"], 0, 86400)
        assert db.execute("SELECT at FROM bulletins").fetchone()[0] == 7 * 3600 + 65 * 60
    finally:
        db.close()


def test_offline_iem_reconstruction_is_labelled_and_never_used_for_E3(tmp_path):
    path = tmp_path / "iem.csv"
    path.write_text("station,valid,tmpc,metar\nLGA,1970-01-01 00:53,20,METAR\nLGA,1970-01-01 01:53,22,METAR\n")
    db = source.open_store(tmp_path / "db.sqlite")
    try:
        source.stage_iem(db, [path], REGISTRY["nyc"], 0, 86400)
        with pytest.raises(StudyError, match="E3 requires"):
            source.windows_for_event(db, REGISTRY["nyc"], 0, 86400, reconstruct_triggers=True)
        db.execute("INSERT INTO observations VALUES (3180,3240,65,1)")
        db.execute("INSERT INTO bands VALUES ('b','yes',NULL,'x','eq',68,69)")
        windows, notes = source.windows_for_event(db, REGISTRY["nyc"], 0, 86400, reconstruct_triggers=True)
        assert notes["E2_source"] == "IEM_RECONSTRUCTION"
        assert [(w.observed, w.detected) for w in windows if w.kind == "E2"] == [(6780, None)]
        assert not any(w.kind == "E3" for w in windows)
    finally:
        db.close()


def test_large_synthetic_date_end_to_end_profile(tmp_path):
    import time
    event = synthetic_event(tmp_path)
    write_rows(Path(event["trades"][0]), ({"asset_id": "yes", "timestamp": str(int((event["start"] + 1) * 1000) + index * 800),
        "price": ".37" if index % 2 else ".57", "size": "1", "side": "SELL" if index % 2 else "BUY",
        "transaction_hash": f"synthetic-{index}"} for index in range(100_000)))
    started = time.monotonic()
    result = study.run_study([event], tmp_path / "output", replicates=10)
    resources = result["resources"]
    assert resources["peak_python_allocated_bytes"] < 256 * 1024 * 1024
    assert resources["process_lifetime_peak_working_set_bytes"] > 0
    assert result["events"][0]["exclusions"] == []
    assert result["R"]["d1.5_conservative/midrange"]["sufficient_statistics"]["total"]["filled_shares"] > 1000
    print(json.dumps({"synthetic_large_date": {"trades": 100000, "book_samples": 1440,
        "seconds": round(time.monotonic() - started, 3), **resources}}))
