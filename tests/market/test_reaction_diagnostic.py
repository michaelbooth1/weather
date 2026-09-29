"""Fixture tests for the 111f competitor-reaction and latency diagnostic."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest

from weather.market import reaction_diagnostic as rd
from weather.market.maker_evidence_store import EvidenceStore, encoded
from weather.market.reaction_diagnostic_io import Budget, allow_list, read_bands
from weather.market.reward_share_estimate import order_score, q_min, share_of, side_score

COND_A = "0x" + "a" * 64
COND_B = "0x" + "b" * 64
YES_A, NO_A, YES_B, NO_B = "111", "112", "221", "222"
SLUG = "highest-temperature-in-toronto-on-september-28-2026"


def utc(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


class Clock:
    def __init__(self, start):
        self.now = start

    def __call__(self):
        return self.now


def book(token, condition, bids, asks):
    return {"asset_id": token, "market": condition, "tick_size": "0.01", "min_order_size": "5",
            "bids": [{"price": str(p), "size": str(s)} for p, s in bids],
            "asks": [{"price": str(p), "size": str(s)} for p, s in asks]}


def write_88a(root, frames, universe):
    """frames: [(utc datetime, [book dict, ...])] written with the production 88a writer."""
    clock = Clock(frames[0][0])
    store = EvidenceStore(root, clock=clock)
    for when, books in frames:
        clock.now = when
        store.event("universe", {"city": "toronto", "bands": universe}, partition="toronto")
        store.record("books", json.dumps(books).encode())
    store.seal()


def universe_rows(*pairs):
    return [{"condition_id": cid, "city": "toronto", "day_ahead": 0, "event_slug": SLUG, "tokens": [yes, no]}
            for cid, yes, no in pairs]


def canonical(row):
    return (json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str) + "\n").encode()


def write_journal(folder, events, *, prediction=True):
    """RE-1 HoldJournal format: canonical lines with a sha256 hash chain."""
    folder.mkdir(parents=True)
    raw, previous = b"", None
    for index, (when, event, fields) in enumerate(events):
        row = {"schema_version": "mm_stage2_hold_v1", "kind": "journal", "sequence": index,
               "previous_sha256": previous, "recorded_at_utc": when.isoformat(), "event": event, **fields}
        line = canonical(row)
        raw += line
        previous = hashlib.sha256(line).hexdigest()
    (folder / "journal.jsonl").write_bytes(raw)
    if prediction:
        (folder / "prediction.json").write_bytes(canonical({"journal_sha256": hashlib.sha256(raw).hexdigest()}))


TERMS = {"quote_inputs": {"reward_min_size": "20", "reward_max_spread_cents": "3.5", "reward_rate_per_day": "50"}}


def session_events(start, *, minutes=10):
    events = [(start, "opened", {"scope": {"condition_id": COND_A, "token_ids": [YES_A, NO_A]}, "mode": "live"}),
              (start, "submit_market_snapshot", {"snapshot": TERMS})]
    for token, price, oid in ((YES_A, "0.47", "o1"), (NO_A, "0.49", "o2")):
        events.append((start, "submit_request", {"request": {"token_id": token, "price": price, "size": "20"}}))
        events.append((start + timedelta(seconds=1), "submit_response",
                       {"response": {"id": oid, "status": "live", "success": True}}))
    for minute in range(1, minutes):
        events.append((start + timedelta(minutes=minute, seconds=5), "minute",
                       {"snapshot": TERMS, "observation": {"share_many": 1.0 if minute < 3 else 0.25,
                                                           "share_single": 1.0}}))
    events.append((start + timedelta(minutes=minutes), "terminal", {"reason": "deadline"}))
    return events


def expected_share(bids, asks, yes=0.47, no=0.49, size=20.0, minimum=20.0, maximum=3.5):
    mid = (max(p for p, s in bids if s >= minimum) + min(p for p, s in asks if s >= minimum)) / 2
    comp_bids = [(p, s - size if abs(p - yes) < 1e-9 else s) for p, s in bids]
    comp_asks = [(p, s - size if abs(p - (1 - no)) < 1e-9 else s) for p, s in asks]
    sides = [side_score([x for x in levels if x[1] > 0], mid, maximum, minimum)[0] for levels in (comp_bids, comp_asks)]
    own = q_min(order_score(size, (mid - yes) * 100, maximum, minimum),
                order_score(size, (1 - mid - no) * 100, maximum, minimum), mid)
    return share_of(own, sum(sides) / 2)


@pytest.fixture
def reaction_inputs(tmp_path):
    start = utc("2026-09-24T12:00:00")
    write_journal(tmp_path / "re1-analysis-copy" / "session-1", session_events(start))
    alone = ([(0.47, 20)], [(0.51, 20)])
    crowded = ([(0.47, 20), (0.48, 100)], [(0.51, 20), (0.50, 100)])
    frames = []
    for minute in range(0, 10):
        bids, asks = alone if minute < 3 else crowded
        frames.append((start + timedelta(minutes=minute, seconds=30), [book(YES_A, COND_A, bids, asks)]))
    write_88a(tmp_path / "maker_evidence", frames, universe_rows((COND_A, YES_A, NO_A)))
    return tmp_path, alone, crowded


def test_allow_list_refuses_panel_dates_and_non_calibration_latency():
    with pytest.raises(ValueError, match="quote-panel"):
        allow_list(["2026-09-24", "2026-10-01"])
    with pytest.raises(ValueError, match="calibration"):
        allow_list(["2026-09-24"], calibration_only=True)
    assert allow_list(["2026-09-29", "2026-09-27"], calibration_only=True) == ("2026-09-27", "2026-09-29")
    assert allow_list(["2026-10-15"]) == ("2026-10-15",)


def test_reaction_measures_share_decay_and_k(reaction_inputs):
    root, alone, crowded = reaction_inputs
    report = rd.run_reaction(root / "re1-analysis-copy", root / "maker_evidence", ("2026-09-24",))
    assert report["verdict"] == "ESTIMATED"
    series = report["series_88a_books"]
    curve = {r["minute"]: r for r in series["curve"] if r["samples"]}
    first, later = expected_share(*alone), expected_share(*crowded)
    assert curve[0]["mean_share_many"] == pytest.approx(first) == pytest.approx(1.0)
    assert curve[5]["mean_share_many"] == pytest.approx(later)
    assert later < 0.5
    assert curve[5]["own_quote_visible_fraction"] == 1.0
    assert (curve[0]["sessions"], curve[0]["bands"]) == (1, 1)
    assert series["k_pooled"] == pytest.approx((3 * first + 7 * later) / 10 / first)
    assert series["k_interval"]["ci95"] is None  # one date x one market: no interval claimed
    journal = report["series_re1_journal_books"]
    assert journal["k_pooled"] == pytest.approx((2 * 1.0 + 7 * 0.25) / 9)
    assert report["overlap"][0]["episodes_with_88a_books"] == 1


def test_reaction_reports_no_overlap_instead_of_substituting(tmp_path):
    start = utc("2026-09-24T12:00:00")
    write_journal(tmp_path / "re1-analysis-copy" / "session-1", session_events(start))
    later = utc("2026-09-25T07:00:00")
    write_88a(tmp_path / "maker_evidence", [(later, [book(YES_A, COND_A, [(0.47, 50)], [(0.51, 50)])])],
              universe_rows((COND_A, YES_A, NO_A)))
    report = rd.run_reaction(tmp_path / "re1-analysis-copy", tmp_path / "maker_evidence",
                             ("2026-09-24", "2026-09-25"))
    assert report["verdict"] == "NO_OVERLAP"
    assert report["series_88a_books"]["k_pooled"] is None
    assert report["series_re1_journal_books"]["episodes_with_k"] == 1  # labelled, not substituted


def test_reaction_refuses_broken_chain_and_skips_unlisted_dates(tmp_path):
    base = tmp_path / "re1-analysis-copy"
    write_journal(base / "session-1", session_events(utc("2026-09-24T12:00:00")))
    write_journal(base / "session-2", session_events(utc("2026-09-23T12:00:00")))
    write_journal(base / "session-3", session_events(utc("2026-09-24T14:00:00")), prediction=False)
    journal = base / "session-3" / "journal.jsonl"
    journal.write_bytes(journal.read_bytes().replace(b'"live"', b'"LIVE"', 1))
    write_88a(tmp_path / "maker_evidence", [(utc("2026-09-24T12:00:30"), [])], [])
    report = rd.run_reaction(base, tmp_path / "maker_evidence", ("2026-09-24",))
    assert report["sessions_outside_allow_list"] == ["session-2"]
    assert report["sessions_refused"] == [{"session": "session-3", "reason": "journal_chain_broken"}]


def test_reaction_requires_analysis_copy(tmp_path):
    (tmp_path / "live-root").mkdir()
    with pytest.raises(ValueError, match="analysis_copy"):
        rd.run_reaction(tmp_path / "live-root", tmp_path, ("2026-09-24",))


def write_latency_inputs(tmp_path, *, trigger_at, frames_a, frames_b, extra_triggers=()):
    snapshots = tmp_path / "snapshots"
    (snapshots / SLUG).mkdir(parents=True)
    header = "event_slug,captured_at_utc,condition_id,bin_kind,bin_value_c,bin_value_hi_c,range_label\n"
    rows = "".join(f"{SLUG},2026-09-28T10:00:00+00:00,{cid},eq,{v},{v},\"{v}C\"\n"
                   for cid, v in ((COND_A, 20), (COND_B, 21)))
    (snapshots / SLUG / "snapshots_long.csv").write_text(header + rows, encoding="utf-8")
    records = []
    for when, prev, cur in ((trigger_at, 20.0, 21.0), *extra_triggers):
        trigger = {"reason": "wu_history_high_increased", "source": "wu_history", "previous_value": prev,
                   "current_value": cur, "market_id": "toronto", "event_slug": SLUG, "target_date": "2026-09-28",
                   "unit": "C", "current_captured_at_utc": when.isoformat()}
        records.append({"record_type": "observation_trigger_event", "triggered_at_utc": when.isoformat(),
                        "market_id": "toronto", "event_slug": SLUG,
                        "trigger_context": {"reason": trigger["reason"], "triggers": [trigger]}})
    (snapshots / "observation_triggers.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records),
                                                         encoding="utf-8")
    frames = {}
    for token, cond, series in ((YES_A, COND_A, frames_a), (YES_B, COND_B, frames_b)):
        for when, mid in series:
            frames.setdefault(when, []).append(book(token, cond, [(round(mid - 0.01, 2), 50)],
                                                    [(round(mid + 0.01, 2), 50)]))
    write_88a(tmp_path / "maker_evidence", sorted(frames.items()),
              universe_rows((COND_A, YES_A, NO_A), (COND_B, YES_B, NO_B)))
    return snapshots


def test_latency_measures_lag_and_pre_trigger_decidedness(tmp_path):
    t0 = utc("2026-09-28T15:00:00")
    snapshots = write_latency_inputs(
        tmp_path, trigger_at=t0,
        frames_a=[(t0 - timedelta(minutes=2), 0.95), (t0 + timedelta(minutes=2), 0.60)],
        frames_b=[(t0 - timedelta(minutes=2), 0.30), (t0 + timedelta(minutes=1), 0.30),
                  (t0 + timedelta(minutes=3), 0.45)],
        extra_triggers=[(utc("2026-09-30T15:00:00"), 21.0, 22.0)])
    report = rd.run_latency(tmp_path / "maker_evidence", snapshots, [snapshots / "observation_triggers.jsonl"],
                            ("2026-09-28",))
    assert report["verdict"] == "MEASURED"
    assert report["triggers"] == 1  # the panel-date trigger is discarded before parsing
    rows = {r["role"]: r for r in report["rows"]}
    assert rows["new_high_band"]["condition_id"] == COND_B
    assert (rows["new_high_band"]["lag_seconds"], rows["new_high_band"]["direction"]) == (180.0, "up")
    assert rows["new_high_band"]["pre_outside_0_10_0_90"] is False
    assert rows["previous_high_band"]["condition_id"] == COND_A
    assert (rows["previous_high_band"]["lag_seconds"], rows["previous_high_band"]["direction"]) == (120.0, "down")
    assert rows["previous_high_band"]["pre_outside_0_10_0_90"] is True
    summary = {s["role"]: s for s in report["summary"]}
    assert summary["new_high_band"]["lag_seconds"]["median"] == 180.0
    assert summary["previous_high_band"]["pre_outside_fraction"] == 1.0


def test_latency_censors_windows_that_would_reach_a_disallowed_date(tmp_path):
    t0 = utc("2026-09-29T23:30:00")
    snapshots = write_latency_inputs(
        tmp_path, trigger_at=t0, frames_a=[(t0 - timedelta(minutes=1), 0.40)],
        frames_b=[(t0 - timedelta(minutes=1), 0.30), (t0 + timedelta(minutes=5), 0.30)])
    report = rd.run_latency(tmp_path / "maker_evidence", snapshots, [snapshots / "observation_triggers.jsonl"],
                            ("2026-09-29",))
    statuses = {r["role"]: r["status"] for r in report["rows"]}
    assert statuses == {"new_high_band": "censored_by_allow_list", "previous_high_band": "censored_by_allow_list"}
    assert report["verdict"] == "NO_MEASURED_MOVE"


def test_panel_date_folder_is_never_opened(tmp_path, monkeypatch):
    t0 = utc("2026-09-28T15:00:00")
    snapshots = write_latency_inputs(tmp_path, trigger_at=t0, frames_a=[], frames_b=[(t0, 0.3)])
    panel = tmp_path / "maker_evidence" / "2026-09-30" / ("00-" + "0" * 12)
    panel.mkdir(parents=True)
    (panel / "manifest.json").write_text("not json", encoding="utf-8")
    report = rd.run_latency(tmp_path / "maker_evidence", snapshots, [snapshots / "observation_triggers.jsonl"],
                            ("2026-09-28",))
    assert report["triggers"] == 1
    assert report["input"]["coverage"]["books.sealed_segments"] >= 1


def test_band_rows_captured_on_panel_dates_are_skipped(tmp_path):
    folder = tmp_path / SLUG
    folder.mkdir()
    (folder / "snapshots_long.csv").write_text(
        "event_slug,captured_at_utc,condition_id,bin_kind,bin_value_c,bin_value_hi_c\n"
        f"{SLUG},2026-09-28T10:00:00+00:00,{COND_A},eq,20,20\n"
        f"{SLUG},2026-10-01T10:00:00+00:00,{COND_B},eq,21,21\n", encoding="utf-8")
    bands, status = read_bands(tmp_path, SLUG, Budget())
    assert status == "ok" and set(bands) == {COND_A}


def test_cli_writes_once_and_refuses_output_inside_inputs(reaction_inputs, capsys):
    root, _, _ = reaction_inputs
    argv = ["reaction", "--date", "2026-09-24", "--re1-root", str(root / "re1-analysis-copy"),
            "--maker-evidence-root", str(root / "maker_evidence"), "--out-dir", str(root / "out")]
    assert rd.main(argv) == 0
    report = json.loads((root / "out" / "reaction.json").read_text(encoding="utf-8"))
    assert report["schema_version"] == "competitor_reaction_diagnostic_v0.1"
    assert "Verdict: ESTIMATED" in (root / "out" / "reaction.md").read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        rd.main(argv)
    inside = argv[:-1] + [str(root / "maker_evidence" / "out")]
    with pytest.raises(ValueError, match="inside an input root"):
        rd.main(inside)
    with pytest.raises(SystemExit):
        rd.main(["reaction", "--date", "2026-10-02", *argv[3:]])


def test_cli_refuses_when_the_input_budget_is_exhausted(reaction_inputs, capsys):
    root, _, _ = reaction_inputs
    code = rd.main(["reaction", "--date", "2026-09-24", "--re1-root", str(root / "re1-analysis-copy"),
                    "--maker-evidence-root", str(root / "maker_evidence"), "--out-dir", str(root / "out2"),
                    "--max-input-bytes", "512"])
    assert code == 2
    assert json.loads(capsys.readouterr().out)["refused"] == "input_byte_cap"
    assert not (root / "out2").exists()


def test_budget_refuses_caps_above_plugin_limits():
    with pytest.raises(ValueError):
        Budget(max_input_bytes=2 * 1024**3)
    assert encoded({"a": 1}) == b'{"a":1}'
