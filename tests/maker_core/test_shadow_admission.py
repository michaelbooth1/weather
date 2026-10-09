"""Shadow scoring embargo scopes and the parity-day admission. Fictional dates and injected windows only.

Guards: maker shadow evidence embargo and parity admission (docs/operations/maker-shadow-runner.md, Embargo;
  owner B4 2026-10-08: parity days scorable outcome-blind while reserved windows stay protected).
"""
from datetime import date, datetime, timedelta, timezone
import json

import pytest

from maker_core.shadow import admission as adm
from maker_core.shadow.admission import (
    EMBARGO_WINDOWS, EMBARGOED_UTC_DAYS, FULL, OUTCOME, PARITY_CLOCK_SCHEMA, ParityClock, admit_parity_day,
    assert_outcome_blind, bind_parity_tapes, embargo_reason, embargo_scope, parity_clock_from, run_started, utc_day)
from maker_core.shadow.tape import TapeWriter, sealed_tapes

# Fictional windows: a full window, then an outcome window sharing its last day (as the real W1/W2 share 10-15).
WINDOWS = (("2031-03-01", "2031-03-10", FULL, "fictional full"),
           ("2031-03-10", "2031-04-01", OUTCOME, "fictional outcome"))
S = "a" * 40
E = "b" * 40
CFG = "c" * 64
NOW = lambda: datetime(2031, 6, 1, 12, 0, tzinfo=timezone.utc)  # noqa: E731


def clock_mapping(**overrides):
    mapping = {"schema_version": PARITY_CLOCK_SCHEMA, "engine_commit": E, "freeze_utc": "2031-03-12T09:00:00Z",
               "shadow_commit": S, "restart_run_id": "20310312T101500Z-0123abcd", "config_sha256": CFG}
    mapping.update(overrides)
    return mapping


CLOCK = parity_clock_from(clock_mapping())


def tape(day, *, run_id="20310312T101500Z-0123abcd", commit=S, dirty=False, error=None, config=CFG, code=True):
    scope = {"utc_day": day, "run_id": run_id, "config_sha256": config}
    if code:
        scope.update(git_commit=commit, git_dirty=dirty, git_error=error)
    return {"tape": f"{day}-{run_id}.tape.jsonl", "sha256": "0" * 64,
            "rows": [{"event": "opened", "scope": scope}, {"event": "terminal"}]}


def test_real_windows_keep_their_dates_and_scope_w1_full_w2_outcome():
    assert [(s, e, scope) for s, e, scope, _ in EMBARGO_WINDOWS] == [
        ("2026-09-30", "2026-10-15", FULL), ("2026-10-15", "2026-11-13", OUTCOME)]
    assert EMBARGOED_UTC_DAYS == tuple((s, e, r) for s, e, _, r in EMBARGO_WINDOWS)
    assert embargo_scope("2026-10-15") == FULL  # the shared day takes the most restrictive scope


def test_weather_panel_reexports_the_core_windows():
    from weather.market import maker_shadow_panel
    assert maker_shadow_panel.EMBARGOED_UTC_DAYS is EMBARGOED_UTC_DAYS
    assert maker_shadow_panel.embargo_reason is embargo_reason


@pytest.mark.parametrize("value", ["2031-3-05", "20310305", "2031-03-05T00:00", " 2031-03-05", "x", ""])
def test_non_canonical_days_are_refused(value):
    with pytest.raises(ValueError, match="utc_day_not_canonical"):
        utc_day(value)
    with pytest.raises(ValueError, match="utc_day_not_canonical"):
        admit_parity_day(value, CLOCK, now=NOW, windows=WINDOWS)


def test_embargo_reason_and_scope_on_injected_windows():
    assert embargo_reason("2031-02-28", WINDOWS) is None and embargo_scope("2031-04-02", WINDOWS) is None
    assert embargo_scope("2031-03-01", WINDOWS) == FULL and embargo_scope("2031-03-10", WINDOWS) == FULL
    assert embargo_scope("2031-03-11", WINDOWS) == OUTCOME and embargo_scope("2031-04-01", WINDOWS) == OUTCOME
    assert embargo_reason(date(2031, 3, 20), WINDOWS) == "fictional outcome"


@pytest.mark.parametrize("day, refused", [
    ("2031-03-05", "embargoed_utc_day"),       # full window: parity refused too
    ("2031-03-10", "embargoed_utc_day"),       # shared day: full wins
    ("2031-03-12", "before_parity_clock"),     # restart day never counts
    ("2031-06-01", "utc_day_not_closed"),      # today
    ("2031-06-02", "utc_day_not_closed"),
])
def test_parity_admission_refusals(day, refused):
    result = admit_parity_day(day, CLOCK, now=NOW, windows=WINDOWS)
    assert result.refused == refused and not result.admitted


def test_parity_admitted_in_outcome_window_with_outcomes_withheld_and_open_day_plain():
    inside = admit_parity_day("2031-03-13", CLOCK, now=NOW, windows=WINDOWS)
    assert inside.admitted and inside.withhold_outcomes and inside.reason == "fictional outcome"
    after = admit_parity_day("2031-04-02", CLOCK, now=NOW, windows=WINDOWS)
    assert after.admitted and not after.withhold_outcomes and after.reason is None


def test_no_clock_means_parity_not_started_even_outside_windows():
    assert admit_parity_day("2031-05-01", None, now=NOW, windows=WINDOWS).refused == "parity_clock_not_started"
    with pytest.raises(TypeError):
        admit_parity_day("2031-05-01", clock_mapping(), now=NOW, windows=WINDOWS)


def test_full_window_refusal_precedes_the_clock_check():
    assert admit_parity_day("2031-03-05", None, now=NOW, windows=WINDOWS).refused == "embargoed_utc_day"


def test_clock_first_countable_day_is_the_day_after_the_restart_run():
    assert CLOCK.restart_utc == datetime(2031, 3, 12, 10, 15, tzinfo=timezone.utc)
    assert CLOCK.first_countable_day == "2031-03-13"
    late = parity_clock_from(clock_mapping(restart_run_id="20310312T235959Z-0123abcd"))
    assert late.first_countable_day == "2031-03-13"


@pytest.mark.parametrize("overrides, error", [
    ({"extra": 1}, "parity_clock_fields"),
    ({"schema_version": "v0"}, "parity_clock_schema"),
    ({"engine_commit": "B" * 40}, "parity_clock_engine_commit_invalid"),
    ({"shadow_commit": "a" * 12}, "parity_clock_shadow_commit_invalid"),
    ({"config_sha256": "c" * 63}, "parity_clock_config_sha256_invalid"),
    ({"freeze_utc": "2031-03-12T09:00:00"}, "parity_clock_time_not_utc"),
    ({"freeze_utc": "2031-03-12T09:00:00+01:00"}, "parity_clock_time_not_utc"),
    ({"freeze_utc": "soon"}, "parity_clock_time_invalid"),
    ({"restart_run_id": "r1"}, "parity_clock_restart_run_id_invalid"),
    ({"restart_run_id": "20310312T085959Z-0123abcd"}, "parity_clock_restart_before_freeze"),
])
def test_parity_clock_loader_is_strict(overrides, error):
    with pytest.raises(ValueError, match=error):
        parity_clock_from(clock_mapping(**overrides))


def test_parity_clock_loader_refuses_missing_field():
    mapping = clock_mapping()
    del mapping["config_sha256"]
    with pytest.raises(ValueError, match="parity_clock_fields"):
        parity_clock_from(mapping)


def test_run_started_parses_only_runner_run_ids():
    assert run_started("20310312T101500Z-0123abcd") == datetime(2031, 3, 12, 10, 15, tzinfo=timezone.utc)
    assert run_started("20310312T101500Z-0123ABCD") is None and run_started(None) is None


ADMITTED = admit_parity_day("2031-03-13", CLOCK, now=NOW, windows=WINDOWS)


def test_bound_tapes_pass_including_a_later_respawn_on_the_same_commit():
    respawn = tape("2031-03-13", run_id="20310313T061000Z-feedbeef")
    assert bind_parity_tapes(ADMITTED, [tape("2031-03-13"), respawn], [], CLOCK) is None


@pytest.mark.parametrize("tapes, unsealed, refused", [
    ([tape("2031-03-13")], ["2031-03-13-x.tape.jsonl"], "unsealed_tape"),
    ([], [], "no_sealed_tape"),
    ([tape("2031-03-13", code=False)], [], "code_unbound"),
    ([tape("2031-03-13", commit=None, error="git_missing")], [], "code_unbound"),
    ([tape("2031-03-13", dirty=True)], [], "code_unbound"),
    ([tape("2031-03-13", dirty=None)], [], "code_unbound"),
    ([tape("2031-03-13", error="git_timeout")], [], "code_unbound"),
    ([tape("2031-03-13", commit="d" * 40)], [], "not_parity_commit"),
    ([tape("2031-03-13"), tape("2031-03-13", commit="d" * 40)], [], "not_parity_commit"),
    ([tape("2031-03-12")], [], "tape_day_mismatch"),
    ([tape("2031-03-13", config="e" * 64)], [], "not_parity_config"),
    ([tape("2031-03-13", run_id="r1")], [], "run_unbound"),
    ([tape("2031-03-13", run_id="20310312T080000Z-0123abcd")], [], "run_before_restart"),
])
def test_tape_binding_refusals(tapes, unsealed, refused):
    assert bind_parity_tapes(ADMITTED, tapes, unsealed, CLOCK) == refused


def test_binding_requires_an_admitted_day():
    refused = admit_parity_day("2031-03-05", CLOCK, now=NOW, windows=WINDOWS)
    with pytest.raises(ValueError, match="parity_day_not_admitted"):
        bind_parity_tapes(refused, [tape("2031-03-05")], [], CLOCK)


def test_outcome_fields_refused_on_outcome_window_day_at_any_depth():
    blind = {"utc_day": "2031-03-13", "parity": {"paired": 3, "decision_mismatch": 0, "price_mismatch": 0}}
    assert assert_outcome_blind(blind, ADMITTED) is blind
    for leak in ({"fills": []}, {"diagnostics": {"cash": "1"}}, {"rows": [{"markouts": {}}]},
                 {"strata": {}}, {"x": {"net_pusd": "0"}}, {"settlement": None}):
        with pytest.raises(ValueError, match="parity_report_not_allowlisted"):
            assert_outcome_blind({**blind, **leak}, ADMITTED)
    after = admit_parity_day("2031-04-02", CLOCK, now=NOW, windows=WINDOWS)
    assert assert_outcome_blind({**blind, "fills": []}, after)  # outside the window, outcomes may be reported


def test_parity_reads_only_the_admitted_days_tapes(tmp_path):
    """A real sealed tape of D binds; D-1 and D+1 files are never opened (they are not even valid tapes)."""
    day = "2031-03-13"
    run_id = "20310313T000000Z-0123abcd"
    start = datetime(2031, 3, 13, 0, 0, tzinfo=timezone.utc)
    writer = TapeWriter(tmp_path, clock=lambda: start, run_id=run_id,
                        scope={"config_sha256": CFG, "git_commit": S, "git_dirty": False, "git_error": None})
    writer.record("minute", start, conditions=[], guard={"action": "ALLOW"}, resting_after={})
    writer.close("completed")
    for other in ("2031-03-12", "2031-03-14"):
        (tmp_path / f"{other}-{run_id}.tape.jsonl").write_bytes(b"not json")
        (tmp_path / f"{other}-{run_id}.seal.json").write_bytes(b"not json")
    tapes, unsealed = sealed_tapes(tmp_path, day)
    assert [t["tape"] for t in tapes] == [f"{day}-{run_id}.tape.jsonl"] and unsealed == []
    assert bind_parity_tapes(ADMITTED, tapes, unsealed, CLOCK) is None
    assert json.loads(json.dumps(adm.tape_code(tapes[0])))["git_commit"] == S


def test_admission_module_is_domain_neutral():
    source = open(adm.__file__, encoding="utf-8").read()
    assert "import weather" not in source and "from weather" not in source


def test_restart_day_offset_holds_for_a_restart_just_before_midnight():
    clock = ParityClock(E, datetime(2031, 3, 31, 23, 0, tzinfo=timezone.utc), S, "20310331T235900Z-0123abcd", CFG)
    assert clock.first_countable_day == (date(2031, 3, 31) + timedelta(days=1)).isoformat()
    assert admit_parity_day("2031-03-31", clock, now=NOW, windows=WINDOWS).refused == "before_parity_clock"
    assert admit_parity_day("2031-04-01", clock, now=NOW, windows=WINDOWS).admitted


# ---- fix round (Defender M1/M2/N1/N2/N6) ----

FULL_REPORT = {
    "schema_version": "maker_core.shadow_parity.v0", "label": "PARITY_OUTCOME_BLIND", "utc_day": "2031-03-13",
    "verdict": "PASS", "refused": None, "engine_commit": E, "shadow_commit": S, "config_sha256": CFG,
    "parity": {"paired": 3, "unevaluated": 1, "shadow_only": 0, "replay_only": 0, "decision_mismatch": 0,
               "price_mismatch": 0, "parity": 3, "exact_equal": 2, "max_price_diff_ticks": adm.Decimal("1"),
               "field_disagreements": {"reasons": 1, "sizes": 0}},
    "tapes": [{"tape": "2031-03-13-20310312T101500Z-0123abcd.tape.jsonl", "sha256": "0" * 64, "git_commit": S,
               "git_dirty": False, "git_error": None}],
    "code": {"git_commits": [S], "tapes": 1, "dirty_tapes": 0, "unbound_tapes": 0},
}


def test_allowlisted_parity_report_passes_on_an_outcome_day():
    assert assert_outcome_blind(FULL_REPORT, ADMITTED) is FULL_REPORT


class Obj:
    fills = [1]


@pytest.mark.parametrize("leak", [
    {"paper_fills": [1]}, {"markout_1m": "0.01"}, {"realized": "3"}, {"cash_pusd": "5"}, {"Fills": []},
    {"paper": {"summary": {"pnl_pusd": "1"}}}, {"inputs": {"portfolio": {"wallet_used": 1}}},
    {"resting_after": {"c": []}}, {"fill_seen": True}, {("fills",): 1}, {1: 2}, {frozenset({"fills"}): 1},
    {"parity": {"paired": 1, ("fills",): 1}}, {"parity": {"paired": 1, "cash_pusd": 1}},
    {"tapes": [("fills", [1])]}, {"tapes": ({"tape": "x"},)}, {"code": {"git_commits": frozenset({S})}},
    {"label": '{"fills": [1]}'}, {"refused": "pnl 5"}, {"verdict": "[1,2]"}, {"utc_day": 'a"b'},
    {"parity": {"paired": True}}, {"parity": {"paired": -1}}, {"parity": {"paired": 1.0}},
    {"parity": {"max_price_diff_ticks": adm.Decimal("NaN")}}, {"parity": Obj()}, {"label": Obj()},
    {"tapes": [{"tape": "t", "git_dirty": "false"}]}, {"shadow_commit": "A" * 40},
])
def test_anything_outside_the_allowlist_is_refused(leak):
    with pytest.raises(ValueError, match="parity_report_not_allowlisted"):
        assert_outcome_blind({**FULL_REPORT, **leak}, ADMITTED)


def test_dataclass_and_non_dict_reports_are_refused():
    from dataclasses import dataclass

    @dataclass
    class Report:
        fills: list

    for report in (Report([1]), [FULL_REPORT], (FULL_REPORT,), json.dumps(FULL_REPORT, default=str)):
        with pytest.raises(ValueError, match="parity_report_not_allowlisted"):
            assert_outcome_blind(report, ADMITTED)


def test_real_tape_paper_and_inputs_blocks_are_refused(tmp_path):
    """A real runner minute (fixture rig, paper ledger) copied into a report is refused, block by block."""
    from .fixtures.shadow_rig import MARKETS, NOW as RIG_NOW, paper_ledger, rig
    runner, *_ = rig(tmp_path, paper=paper_ledger())
    record = json.loads(json.dumps(runner.step(RIG_NOW, MARKETS), default=str))
    condition = record["conditions"][0]
    assert {"cash_pusd", "pnl_pusd", "trade_count"} <= set(record["paper"])
    blocks = {"paper": record["paper"], "inputs": condition["inputs"], "resting_after": record["resting_after"],
              "decision": condition.get("decision"), "record": record}
    for name, block in blocks.items():
        with pytest.raises(ValueError, match="parity_report_not_allowlisted"):
            assert_outcome_blind({**FULL_REPORT, name: block}, ADMITTED)
        with pytest.raises(ValueError, match="parity_report_not_allowlisted"):
            assert_outcome_blind({**FULL_REPORT, "parity": {**FULL_REPORT["parity"], name: block}}, ADMITTED)


def test_assert_outcome_blind_requires_an_admission():
    with pytest.raises(ValueError, match="parity_day_not_admitted"):
        assert_outcome_blind(FULL_REPORT, None)


@pytest.mark.parametrize("day", ["2026-09-30", "2026-10-01", "2026-10-15", "2026-10-16", "2026-11-13"])
def test_maker_evidence_panel_refuses_embargoed_days_before_any_path(tmp_path, day):
    from weather.market.maker_shadow_panel import MakerEvidencePanel
    with pytest.raises(ValueError, match="embargoed_utc_day"):
        MakerEvidencePanel(tmp_path / "never-created", day, set())
    assert not (tmp_path / "never-created").exists()


@pytest.mark.parametrize("day", ["20310313", "2031-03-13/../2031-03-14", "../x"])
def test_maker_evidence_panel_refuses_non_canonical_days(tmp_path, day):
    from weather.market.maker_shadow_panel import MakerEvidencePanel
    with pytest.raises(ValueError, match="utc_day_not_canonical"):
        MakerEvidencePanel(tmp_path, day, set())


def test_now_is_computed_in_utc_inside_admission():
    west = timezone(timedelta(hours=-5))
    east = timezone(timedelta(hours=5))
    # 2031-05-31 23:30 at UTC-05 is 2031-06-01 04:30 UTC, so 05-31 is closed.
    assert admit_parity_day("2031-05-31", CLOCK, now=lambda: datetime(2031, 5, 31, 23, 30, tzinfo=west),
                            windows=WINDOWS).admitted
    # 2031-06-01 03:00 at UTC+05 is 2031-05-31 22:00 UTC, so 05-31 is still open.
    assert admit_parity_day("2031-05-31", CLOCK, now=lambda: datetime(2031, 6, 1, 3, 0, tzinfo=east),
                            windows=WINDOWS).refused == "utc_day_not_closed"
    with pytest.raises(ValueError, match="parity_now_not_aware"):
        admit_parity_day("2031-05-30", CLOCK, now=lambda: datetime(2031, 6, 1), windows=WINDOWS)
    with pytest.raises(TypeError):
        admit_parity_day("2031-05-30", CLOCK, today=date(2099, 1, 1), windows=WINDOWS)


def test_default_now_is_the_real_utc_clock():
    future = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
    assert admit_parity_day(future, CLOCK, windows=()).refused == "utc_day_not_closed"


def test_bind_refuses_a_clock_other_than_the_admission_clock():
    other = parity_clock_from(clock_mapping(shadow_commit="d" * 40))
    with pytest.raises(ValueError, match="parity_clock_differs_from_admission"):
        bind_parity_tapes(ADMITTED, [tape("2031-03-13", commit="d" * 40)], [], other)
    with pytest.raises(ValueError, match="parity_clock_differs_from_admission"):
        bind_parity_tapes(ADMITTED, [tape("2031-03-13")], [], None)
    assert ADMITTED.clock is CLOCK


def test_impossible_calendar_run_id_is_a_parity_clock_code():
    assert run_started("20311399T000000Z-0123abcd") is None
    with pytest.raises(ValueError, match="parity_clock_restart_run_id_invalid"):
        parity_clock_from(clock_mapping(restart_run_id="20311399T000000Z-0123abcd"))


def test_restart_in_the_freeze_second_but_before_the_freeze_instant_is_refused():
    with pytest.raises(ValueError, match="parity_clock_restart_before_freeze"):
        parity_clock_from(clock_mapping(freeze_utc="2031-03-12T09:00:00.900Z",
                                        restart_run_id="20310312T090000Z-0123abcd"))
    exact = parity_clock_from(clock_mapping(freeze_utc="2031-03-12T09:00:00Z",
                                            restart_run_id="20310312T090000Z-0123abcd"))
    assert exact.restart_utc == exact.freeze_utc


def _write_tape(root, run_id, start, **scope):
    writer = TapeWriter(root, clock=lambda: start, run_id=run_id,
                        scope={"config_sha256": CFG, "git_commit": S, "git_dirty": False, "git_error": None, **scope})
    writer.record("minute", start, conditions=[], guard={"action": "ALLOW"}, resting_after={})
    writer.close("completed")


def test_open_parity_tapes_requires_an_admitted_admission_and_binds(tmp_path):
    _write_tape(tmp_path, "20310313T000000Z-0123abcd", datetime(2031, 3, 13, tzinfo=timezone.utc))
    (tmp_path / "2031-03-12-20310312T000000Z-0123abcd.tape.jsonl").write_bytes(b"not json")
    tapes = adm.open_parity_tapes(tmp_path, ADMITTED)
    assert [t["tape"] for t in tapes] == ["2031-03-13-20310313T000000Z-0123abcd.tape.jsonl"]
    for bad in (None, "2031-03-13", admit_parity_day("2031-03-05", CLOCK, now=NOW, windows=WINDOWS),
                admit_parity_day("2031-03-12", CLOCK, now=NOW, windows=WINDOWS)):
        with pytest.raises(ValueError, match="parity_day_not_admitted"):
            adm.open_parity_tapes(tmp_path, bad)


def test_open_parity_tapes_refuses_an_unbound_day(tmp_path):
    _write_tape(tmp_path, "20310313T000000Z-0123abcd", datetime(2031, 3, 13, tzinfo=timezone.utc), git_dirty=True)
    with pytest.raises(ValueError, match="code_unbound"):
        adm.open_parity_tapes(tmp_path, ADMITTED)
