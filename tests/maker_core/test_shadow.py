from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from itertools import groupby
import json

import pytest

from maker_core.evidence.journal import canonical_bytes, digest
from maker_core.replay.bundle import CapturedRecord, Condition, timestamp
from maker_core.replay.lifecycle import ReplayConfig
from maker_core.shadow.codec import checked, decode
from maker_core.shadow.session import Manifest, Tape, verified
from maker_core.shadow.runner import Runner
from maker_core.shadow.agreement import evaluate
from tests.maker_core.fixtures.replay_scenario import Scenario


def manifest(scenario, **changes):
    value = Manifest("fixture", "1"*40, "fixture", "synthetic", "2"*64, "3"*64,
        tuple(Condition(c["condition_id"], c["market_id"], c["domain_id"], timestamp(c["active_from"]),
                        timestamp(c["active_until"])) for c in scenario.conditions),
        tuple((c["condition_id"], "2020-01-03") for c in scenario.conditions),
        scenario.start, scenario.at(scenario.minutes*60),
        ReplayConfig(hazard_per_minute=.001, max_book_gap_seconds=10), "synthetic", mode="drill")
    return replace(value, **changes)


def rows(scenario):
    return [CapturedRecord(r["sequence"], timestamp(r["captured_at"]), r["condition_id"], r["kind"],
                           r["payload"], r["payload_sha256"], r["source_hashes"])
            for r in scenario.records]


def run(tmp_path, scenario, **kwargs):
    tape = Tape(tmp_path / "session", manifest(scenario, **kwargs))
    runner = Runner(tape.manifest, tape)
    for at, batch in groupby(sorted(rows(scenario), key=lambda r: (r.captured_at, r.sequence)),
                            key=lambda r: r.captured_at):
        runner.advance(at, tuple(batch))
    final = runner.stop(scenario.at(scenario.minutes*60), "interval_end")
    return runner, final


def test_exact_decision_round_trip_survives_guard(inputs):
    projection = checked(inputs)
    assert "outcome_tokens" not in canonical_bytes(projection).decode()
    restored = decode(projection)
    assert restored == inputs
    assert digest(restored) == digest(inputs)
    with pytest.raises(ValueError, match="secret_guard"):
        checked({"api_key": "do-not-store"})


def test_exact_replay_and_economics_embargo(tmp_path):
    s = Scenario(markets=("a",), minutes=2)
    s.book("a", 0)
    s.book("a", 5)
    runner, final = run(tmp_path, s)
    m, trace, artifacts, _ = verified(tmp_path / "session", final)
    decisions = [r for r in trace if r["event"] == "decision"]
    assert any(r["decision"]["action"] == "QUOTE" for r in decisions)
    assert any(r["at"] == s.at(15).isoformat() and r["decision"]["reasons"] == ["CAPTURE_GAP"] for r in decisions)
    assert any(r["event"] == "gap" for r in trace)
    assert len([r for r in trace if r["event"] == "minute"]) == 2
    for row in decisions:
        if row["typed_input"]:
            assert digest(artifacts[row["typed_input"]]) == row["decision"]["input_hash"]
    report = evaluate(tmp_path / "session", final, tmp_path / "evaluation")
    assert report["status"] == "PASS", report
    assert report["economics"] == report["policy_comparison"] == "NOT_RUN"
    assert report["qualified_dates"] == 0


def test_terms_change_immediately_withdraws_before_cooldown(tmp_path):
    s = Scenario(markets=("a",), minutes=1)
    s.book("a", 0)
    s.terms("a", 2, minimum=Decimal(200))
    _, final = run(tmp_path, s)
    _, trace, _, _ = verified(tmp_path / "session", final)
    assert any(r["event"] == "decision" and r["at"] == s.at(2).isoformat()
               and r["decision"]["reasons"] == ["TERMS_CHANGED"] and r["decision"]["action"] == "CANCEL"
               for r in trace)


@pytest.mark.parametrize("injection", ["kill", "cancel_all", "gap", "lost_ack"])
def test_drills_stop_both_states_and_refuse_restart(tmp_path, injection):
    s = Scenario(markets=("a", "b"), minutes=2)
    s.book("a", 0)
    s.book("b", 0)
    tape = Tape(tmp_path / "session", manifest(s))
    runner = Runner(tape.manifest, tape)
    runner.advance(s.start, rows(s))
    assert runner.engine.states[s.cid("a")].legs
    final = runner.drill(s.at(3), injection)
    assert runner.stopped
    assert all(not st.legs for e in (runner.engine, runner.sensitivity) for st in e.states.values())
    if injection == "lost_ack":
        assert final is None and not (tape.root / "receipt.json").exists()
        assert evaluate(tmp_path / "session", "0"*64, tmp_path / "evaluation")["status"] == "INCOMPLETE"
    else:
        assert evaluate(tmp_path / "session", final, tmp_path / "evaluation")["status"] == "PASS"
    with pytest.raises(ValueError):
        runner.advance(s.at(4))
    with pytest.raises(FileExistsError):
        Tape(tmp_path / "session", manifest(s))


def test_tamper_truncation_and_unknown_files_refused(tmp_path):
    s = Scenario(markets=("a",), minutes=1)
    s.book("a", 0)
    _, final = run(tmp_path, s)
    path = tmp_path / "session" / "quotes-00000.jsonl"
    raw = path.read_bytes()
    path.write_bytes(raw.rsplit(b"\n", 2)[0] + b"\n")
    with pytest.raises(ValueError):
        verified(tmp_path / "session", final)
    path.write_bytes(raw)
    (tmp_path / "session" / "extra.json").write_text("{}")
    with pytest.raises(ValueError, match="unlisted"):
        verified(tmp_path / "session", final)


def test_trade_duplicate_and_first_fill_sibling_withdrawal(tmp_path):
    s = Scenario(markets=("a",), minutes=1)
    s.book("a", 0)
    s.trade("a", 3, trade_id="print")
    s.trade("a", 3, trade_id="print")
    runner, final = run(tmp_path, s)
    assert len(runner.engine.states[s.cid("a")].lots) == 1
    assert runner.engine.cash < 100
    assert evaluate(tmp_path / "session", final, tmp_path / "evaluation")["status"] == "PASS"


def test_journal_failure_leaves_partial_segment_and_poison(tmp_path, monkeypatch):
    s = Scenario(markets=("a",), minutes=1)
    s.book("a", 0)
    tape = Tape(tmp_path / "session", manifest(s))
    runner = Runner(tape.manifest, tape)
    def fail(*args, **kwargs):
        raise OSError("fixture disk failure")
    monkeypatch.setattr(tape.journal, "record", fail)
    with pytest.raises(OSError):
        runner.advance(s.start, rows(s))
    assert tape.failed
    assert not (tape.root / "receipt.json").exists()
    tape.abort()


def test_missing_hazard_refuses_admission():
    s = Scenario(markets=("a",), minutes=1)
    with pytest.raises(ValueError, match="configuration"):
        manifest(s, config=ReplayConfig(max_book_gap_seconds=10))


def test_journal_refuses_silent_redaction(tmp_path):
    s = Scenario(markets=("a",), minutes=1)
    tape = Tape(tmp_path / "session", manifest(s))
    with pytest.raises(ValueError, match="secret_guard_would_change_record"):
        tape.record("unsafe", api_key="fixture-only")
    assert tape.failed
    tape.abort()


def test_cross_midnight_segments_preserve_inventory_and_lineage(tmp_path):
    from datetime import datetime
    s = Scenario(markets=("a",), minutes=2)
    s.book("a", 0)
    s.trade("a", 3)
    shift = timedelta(hours=23, minutes=59)
    def moved(value):
        if isinstance(value, str) and "T" in value and value.endswith("+00:00"):
            return (datetime.fromisoformat(value)+shift).isoformat()
        if isinstance(value, dict): return {k: moved(v) for k, v in value.items()}
        if isinstance(value, list): return [moved(v) for v in value]
        return value
    s.records = moved(s.records)
    s.conditions = moved(s.conditions)
    s.start += shift
    for row in s.records:
        row["payload_sha256"] = digest(row["payload"])
    runner, final = run(tmp_path, s)
    assert len(runner.engine.states[s.cid("a")].lots) == 1
    _, trace, _, receipt = verified(tmp_path / "session", final)
    assert len(receipt["seals"]) == 2
    assert [r["slot"] for r in trace if r["event"] == "minute"] == [s.start.isoformat(), s.at(60).isoformat()]
    assert evaluate(tmp_path / "session", final, tmp_path / "evaluation")["status"] == "PASS"


def test_reconnection_never_restores_unknown_inventory(tmp_path):
    s = Scenario(markets=("a",), minutes=2)
    s.book("a", 0)
    s.trade("a", 3)
    s.book("a", 65)
    runner, final = run(tmp_path, s)
    assert runner.engine.latched[s.cid("a")] == "TRADE_CAPTURE_GAP"
    assert len(runner.engine.states[s.cid("a")].lots) == 1
    _, trace, _, _ = verified(tmp_path / "session", final)
    assert not any(r["event"] == "decision" and r["at"] >= s.at(65).isoformat()
                   and r["decision"]["action"] == "QUOTE" for r in trace)


@pytest.mark.parametrize("event", ["command", "decision", "applied"])
def test_crash_at_each_persistence_boundary_never_replays_intent(tmp_path, event):
    s = Scenario(markets=("a",), minutes=1)
    s.book("a", 0)
    tape = Tape(tmp_path / "session", manifest(s))
    runner = Runner(tape.manifest, tape)
    original = tape.record
    def crash(kind, **payload):
        value = original(kind, **payload)
        if kind == event:
            raise OSError("injected process death")
        return value
    tape.record = crash
    with pytest.raises(OSError):
        runner.advance(s.start, rows(s))
    tape.abort()
    assert evaluate(tape.root, "0"*64, tmp_path / "evaluation")["status"] == "INCOMPLETE"
    with pytest.raises(FileExistsError):
        Tape(tape.root, manifest(s))
