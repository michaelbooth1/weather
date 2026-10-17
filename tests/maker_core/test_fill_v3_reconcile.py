"""DESCRIPTIVE own-session reconciliation: golden result, panel exclusion and embargo refusals (item 330 build 1).

Fictional fixtures only (``fixtures/fill_v3_scenarios.py``): an RE-1-shaped journal with two legs and a replay
bundle whose prints and books give hand-computed answers (see the fixture's comments).

Dated read entry points covered by a refusal test: ``read_journal``, ``admit`` (local quote dates),
``bundle_day``/``read_bundle``, ``reconcile``, ``main`` (CLI) -- plus ``EngineV3`` in ``test_fill_v3_engine``.

Guards: the DESCRIPTIVE own-fill reconcile: golden result, one print per credited fill, the RE-1 writer journal
  shape and hash chain, token-outcome proof, panel exclusions, and reserved-window refusal at every dated entry point.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
import json
from types import SimpleNamespace

import pytest

from maker_core.replay import fill_v3_reconcile as R
from maker_core.replay.fill_v3_embargo import EmbargoRefused
from .fixtures.fill_v3_scenarios import DAY, journal_rows, re1_writer_rows, reconcile_bundle, write_journal

# Hand reasoning for the golden (fixtures/fill_v3_scenarios.py; prints are (s, price, size, outcome)):
# - Predictions (q_ahead, the v2 bounds, fill-v3.0) do not read own fills and are unchanged by attribution.
# - Attribution: each own fill goes to the eligible print with minimum |dt| in [fill - 120 s, fill + 5 s].
#   L1 (YES .48, live 58..600 s, fill 5 at 160 s): window 40..165 holds 90 s (dt -70), 120 s (-40), 150 s (-10)
#     -> the 150 s at-price print. c_at: 90 s add(0, min(25, 20)=20); 150 s add(5, min(8, 20)=8).
#     c_thr: 120 s add(0, min(10, 20)=10). L1 at = 5/28, N 2, k 1.
#   L2 (NO .47, live 60..305 s, fill 20 at 305 s): window 185..310 holds 200 s at price (dt -105) and 300 s
#     through (dt -5) -> the 300 s through print. c_at: 200 s add(0, 6). c_thr: 300 s add(min(20, 12)=12, 12).
#   Totals: c_at 5/34 = 0.147059 over N 3, k 1; c_thr 12/22 = 0.545455 over N 2, k 1.
#   Terciles by q_ahead (cuts 10, 30): T1 = L2 at 0/6; T2 = L1 at 5/28 = 0.178571; T3 empty.
EXPECTED_LEGS = {
    "ord-l1": dict(q_ahead="30", actual_filled="5", end_reason="canceled",
                   predicted={"strictly_through": "10", "at_price": "20", "fill-v3.0": "13"},
                   eligible_prints={"at": 2, "thr": 1}),
    "ord-l2": dict(q_ahead="10", actual_filled="20", end_reason="filled",
                   predicted={"strictly_through": "12", "at_price": "18", "fill-v3.0": "8"},
                   eligible_prints={"at": 1, "thr": 1}),
}


def golden(tmp_path, **kw):
    journal = write_journal(tmp_path / "session-1" / "journal.jsonl", journal_rows())
    return R.reconcile([journal], [reconcile_bundle(tmp_path)], time_zone_name="UTC", **kw)


def test_golden_reconciliation(tmp_path):
    result = golden(tmp_path)
    assert result["label"] == "DESCRIPTIVE" and result["descriptive_only"] is True
    assert "never pooled" in result["no_pooling"]
    assert result["bundle_days"] == ["2020-01-01"]
    assert [leg["order_id"] for leg in result["legs"]] == ["ord-l1", "ord-l2"]  # the refused submit is no leg
    for leg in result["legs"]:
        assert leg["status"] == "RECONCILED"
        for key, value in EXPECTED_LEGS[leg["order_id"]].items():
            assert leg[key] == value, (leg["order_id"], key)
    assert result["c_at"] == {"ratio": "0.147059", "N": 3, "k_prints_with_own_fill": 1,
                              "cp95_nominal": R.clopper_pearson(1, 3)}
    assert result["c_thr"] == {"ratio": "0.545455", "N": 2, "k_prints_with_own_fill": 1,
                               "cp95_nominal": [0.012579, 0.987421]}
    assert "nominal" in result["interval_note"] and "independent" in result["interval_note"]
    assert result["q_ahead_tercile_cuts"] == ["10", "30"]
    tercile = result["c_at_by_q_ahead_tercile"]
    assert (tercile["T1"]["ratio"], tercile["T1"]["N"]) == ("0", 1)
    assert (tercile["T2"]["ratio"], tercile["T2"]["N"]) == ("0.178571", 2)
    assert (tercile["T3"]["ratio"], tercile["T3"]["N"], tercile["T3"]["cp95_nominal"]) == (None, 0, None)
    comparison = result["predicted_vs_actual"]
    assert {m: comparison[m]["predicted_shares"] for m in comparison} == {
        "strictly_through": "22", "at_price": "38", "fill-v3.0": "21"}
    assert all(comparison[m]["actual_shares"] == "25" for m in comparison)
    assert R.encode(result) == R.encode(golden(tmp_path / "again"))


def prints_at(*seconds, price=".47"):
    base = datetime(2020, 1, 1, tzinfo=timezone.utc)
    return [SimpleNamespace(traded_at=base + timedelta(seconds=s), price=D(price)) for s in seconds]


def fill_at(seconds, size="20"):
    return (datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds), D(size), "fill_event")


def test_l2_fill_goes_to_the_nearest_print_not_the_first_eligible():
    # The reviewed misattribution: L2's fill at 305 s has an at-price print 105 s earlier and a through print 5 s
    # earlier. The nearest (through) print takes it; the earlier at-price print gets nothing.
    assert R.attribute_fills([fill_at(305)], prints_at(200, 300)) == [D(0), D(20)]


def test_attribution_ties_go_to_the_earlier_print():
    assert R.attribute_fills([fill_at(100, "4")], prints_at(97, 103)) == [D(4), D(0)]
    assert R.attribute_fills([fill_at(100, "4")], prints_at(100, 100)) == [D(4), D(0)]


def test_attribution_window_is_one_sided_with_a_small_skew():
    assert R.FILL_MATCH_SECONDS == 120 and R.FILL_PRINT_SKEW_SECONDS == 5
    assert R.attribute_fills([fill_at(200)], prints_at(80)) == [D(20)]       # exactly 120 s before: eligible
    assert R.attribute_fills([fill_at(200)], prints_at(79)) == [D(0)]        # 121 s before: outside
    assert R.attribute_fills([fill_at(200)], prints_at(205)) == [D(20)]      # 5 s after (clock skew): eligible
    assert R.attribute_fills([fill_at(200)], prints_at(206)) == [D(0)]       # 6 s after: outside
    assert R.attribute_fills([fill_at(200)], prints_at(150, 206)) == [D(20), D(0)]


def test_each_fill_is_credited_to_one_print_and_prints_can_take_several():
    fills = [fill_at(100, "3"), fill_at(101, "2"), fill_at(300, "7")]
    assert R.attribute_fills(fills, prints_at(99, 290)) == [D(5), D(7)]


def test_clopper_pearson_known_values():
    assert R.clopper_pearson(0, 10) == [0.0, 0.308497]
    assert R.clopper_pearson(5, 10) == [0.187086, 0.812914]
    assert R.clopper_pearson(10, 10) == [0.691503, 1.0]
    assert R.clopper_pearson(1, 4) == [0.006309, 0.80588]
    assert R.clopper_pearson(0, 0) is None
    with pytest.raises(R.ReconcileError):
        R.clopper_pearson(3, 2)


def test_terciles_use_rank_cuts():
    assert R.terciles([]) is None
    assert R.terciles([D(5)]) == (D(5), D(5))
    assert R.terciles([D(v) for v in (9, 1, 5, 3, 7, 2)]) == (D(2), D(5))


def test_cli_writes_a_new_file_and_never_overwrites(tmp_path, capsys):
    journal = write_journal(tmp_path / "session-1" / "journal.jsonl", journal_rows())
    bundle = reconcile_bundle(tmp_path)
    out = tmp_path / "out.json"
    argv = ["--journal", str(journal), "--bundle", str(bundle), "--time-zone", "UTC", "--output", str(out)]
    assert R.main(argv) == 0
    assert json.loads(out.read_bytes())["label"] == "DESCRIPTIVE"
    assert '"label": "DESCRIPTIVE"' in capsys.readouterr().out
    with pytest.raises(FileExistsError):
        R.main(argv)


def test_legs_without_a_covering_bundle_day_are_reported(tmp_path):
    rows = journal_rows()
    journal = write_journal(tmp_path / "s" / "journal.jsonl", rows)
    other = reconcile_bundle(tmp_path, day=date(2020, 1, 2))  # wrong day: no bundle covers the legs
    result = R.reconcile([journal], [other], time_zone_name="UTC")
    assert {leg["status"] for leg in result["legs"]} == {"NO_BUNDLE_DAY"}


def test_conflicting_token_outcomes_refuse(tmp_path):
    rows = journal_rows()
    for row in rows:
        if row["event"] == "terminal_order":
            row["order"]["outcome"] = "Yes"  # the NO token claimed as YES while a fill says No
    journal = write_journal(tmp_path / "s" / "journal.jsonl", rows)
    with pytest.raises(R.ReconcileError, match="conflicting_token_outcome"):
        R.read_journal(journal)


def strip_outcome_proof(rows):
    for row in rows:
        if row["event"] == "terminal_order":
            del row["order"]["outcome"]
        elif row["event"] == "fill":
            del row["user_event"]["outcome"]
    return rows


def test_unproven_token_outcomes_refuse_without_a_declaration(tmp_path):
    journal = write_journal(tmp_path / "s" / "journal.jsonl", strip_outcome_proof(journal_rows()))
    with pytest.raises(R.ReconcileError, match="token_outcomes_unproven"):
        R.read_journal(journal)  # the scope's token order alone proves nothing
    with pytest.raises(R.ReconcileError, match="token_outcomes_unproven"):
        R.reconcile([journal], [reconcile_bundle(tmp_path)], time_zone_name="UTC")


def test_declared_token_outcomes_are_used(tmp_path):
    journal = write_journal(tmp_path / "s" / "journal.jsonl", strip_outcome_proof(journal_rows()))
    session = R.read_journal(journal, {"tok-yes": "YES"})
    assert {leg.order_id: leg.outcome for leg in session.legs} == {"ord-l1": "YES", "ord-l2": "NO"}
    result = R.reconcile([journal], [reconcile_bundle(tmp_path)], time_zone_name="UTC",
                         token_outcomes={"tok-no": "NO"})
    assert result["c_at"]["ratio"] == "0.147059"
    with pytest.raises(R.ReconcileError, match="token_outcome_outside_scope"):
        R.read_journal(journal, {"tok-other": "YES"})
    proven = write_journal(tmp_path / "p" / "journal.jsonl", journal_rows())
    with pytest.raises(R.ReconcileError, match="conflicting_token_outcome"):
        R.read_journal(proven, {"tok-yes": "NO"})  # a declaration never overrides the journal's proof


def test_cli_token_outcomes_flag(tmp_path, capsys):
    journal = write_journal(tmp_path / "s" / "journal.jsonl", strip_outcome_proof(journal_rows()))
    bundle = reconcile_bundle(tmp_path)
    base = ["--journal", str(journal), "--bundle", str(bundle), "--time-zone", "UTC"]
    refused = tmp_path / "refused.json"
    with pytest.raises(R.ReconcileError, match="token_outcomes_unproven"):
        R.main(base + ["--output", str(refused)])
    assert not refused.exists()
    out = tmp_path / "out.json"
    assert R.main(base + ["--token-outcomes", "tok-yes=yes", "--output", str(out)]) == 0
    assert json.loads(out.read_bytes())["c_thr"]["ratio"] == "0.545455"
    for bad, code in (("tok-yes", "token_outcome_value"), ("tok-yes=MAYBE", "token_outcome_value")):
        with pytest.raises(R.ReconcileError, match=code):
            R.parse_token_outcomes([bad])
    with pytest.raises(R.ReconcileError, match="conflicting_token_outcome"):
        R.parse_token_outcomes(["tok-yes=YES", "tok-yes=NO"])
    assert R.parse_token_outcomes([]) is None


# -- the RE-1 writer's row stream (codex/re1-wallet-200-20260923 at 2b9a0ca9e, redacted) ----------------
def test_writer_shaped_session_is_read(tmp_path):
    journal = write_journal(tmp_path / "session-1" / "journal.jsonl", re1_writer_rows())
    session = R.read_journal(journal)
    assert session.condition_id == "c-synthetic"
    legs = {leg.order_id: leg for leg in session.legs}
    assert list(legs) == ["ord-a", "ord-b", "ord-c"]  # raw SDK reply (orderID/success) and rehearsal reply shapes
    assert [(legs[o].outcome, str(legs[o].price)) for o in legs] == [("YES", "0.48"), ("NO", "0.47"), ("YES", "0.47")]
    assert {o: (legs[o].end_reason, int((legs[o].ended_at - DAY).total_seconds())) for o in legs} == {
        "ord-a": ("canceled", 300), "ord-b": ("canceled", 403), "ord-c": ("canceled", 403)}
    assert all(leg.expires_at == DAY + timedelta(seconds=3660) for leg in session.legs)
    R.attach_fills(session, session.legs)
    assert {o: [(int((at - DAY).total_seconds()), str(size), source) for at, size, source in legs[o].fills]
            for o in legs} == {"ord-a": [], "ord-b": [(402, "5", "fill_event")], "ord-c": []}



def test_a_rejected_trade_event_is_read_and_credits_nothing(tmp_path):
    # A FAILED trade reaches the writer's fill path as event_type "rejected" (mm_official_adapter); it carries
    # no fill of its own, so the journal is read and the leg's fills come only from the terminal residual.
    rows = re1_writer_rows()
    for row in rows:
        if row["event"] == "fill":
            row["user_event"].update(event_type="rejected", official_trade_status="FAILED")
        for item in [row.get("response"), row.get("order"), *(row.get("rows") or [])]:
            if isinstance(item, dict) and item.get("id") == "ord-b":
                item["size_matched"] = "0"
    session = R.read_journal(write_journal(tmp_path / "s" / "journal.jsonl", rows))
    R.attach_fills(session, session.legs)
    assert {leg.order_id: leg.fills for leg in session.legs} == {"ord-a": [], "ord-b": [], "ord-c": []}
    assert "rejected" in R.NO_CREDIT_EVENT_TYPES and "rejected" not in R.CREDIT_EVENT_TYPES


def test_credited_fills_above_terminal_size_matched_refuse(tmp_path):
    # A trade_pending credited 5 that later failed: the terminal order shows only 3 matched.
    rows = re1_writer_rows()
    for row in rows:
        if row["event"] == "fill":
            row["user_event"].update(event_type="trade_pending", official_trade_status="MATCHED")
        if row["event"] == "terminal_order" and row["order"]["id"] == "ord-b":
            row["order"]["size_matched"] = "3"
    session = R.read_journal(write_journal(tmp_path / "s" / "journal.jsonl", rows))
    with pytest.raises(R.ReconcileError, match="credited_exceeds_size_matched"):
        R.attach_fills(session, session.legs)
    golden_rows = journal_rows()
    for row in golden_rows:
        if row["event"] == "terminal_order":
            row["order"]["size_matched"] = "12"  # L2 credited 20
    journal = write_journal(tmp_path / "g" / "journal.jsonl", golden_rows)
    with pytest.raises(R.ReconcileError, match="credited_exceeds_size_matched"):
        R.reconcile([journal], [reconcile_bundle(tmp_path)], time_zone_name="UTC")
    equal = re1_writer_rows()  # credited 5 == size_matched 5: no residual, no refusal
    session = R.read_journal(write_journal(tmp_path / "e" / "journal.jsonl", equal))
    R.attach_fills(session, session.legs)

def test_every_writer_event_is_classified():
    events = {row["event"] for row in re1_writer_rows()}
    assert events <= R.READ_EVENTS | R.IGNORED_EVENTS
    assert R.READ_EVENTS.isdisjoint(R.IGNORED_EVENTS)


def mutate(rows, event, change, nth=0):
    hits = [row for row in rows if row["event"] == event]
    change(hits[nth])
    return rows


@pytest.mark.parametrize("change,code", [
    (lambda rows: rows.insert(5, dict(rows[5], event="brand_new_event")), "journal_unknown_event"),
    (lambda rows: mutate(rows, "submit_request", lambda r: r["request"].pop("expiration")), "submit_request_shape"),
    (lambda rows: mutate(rows, "submit_request", lambda r: r.update(extra=1)), "submit_request_shape"),
    (lambda rows: mutate(rows, "submit_response", lambda r: r.update(response=["x"])), "submit_response_shape"),
    (lambda rows: mutate(rows, "cancel_response", lambda r: r["response"].pop("canceled")), "cancel_response_shape"),
    (lambda rows: mutate(rows, "terminal_order", lambda r: r["order"].pop("id")), "terminal_order_shape"),
    (lambda rows: mutate(rows, "fill", lambda r: r.pop("rows")), None),  # (user_event,) is a writer form too
    (lambda rows: mutate(rows, "fill", lambda r: r.update(order={})), "fill_shape"),
    (lambda rows: mutate(rows, "fill", lambda r: r["user_event"].update(event_type="mystery")),
     "fill_user_event_shape"),
    (lambda rows: mutate(rows, "fill", lambda r: r["user_event"].pop("order_id")), "fill_user_event_shape"),
    (lambda rows: mutate(rows, "opened", lambda r: r.pop("mode")), "opened_shape"),
    (lambda rows: mutate(rows, "terminal", lambda r: r.update(unknown_submit=True)), "journal_unknown_submit"),
    (lambda rows: rows.pop(), "journal_without_terminal"),
    (lambda rows: rows.insert(3, dict(rows[-1])), "journal_without_terminal"),
    (lambda rows: rows.pop(0), "journal_without_opened"),
])
def test_writer_shape_mutations_refuse(tmp_path, change, code):
    rows = re1_writer_rows()
    change(rows)
    journal = write_journal(tmp_path / "s" / "journal.jsonl", rows)
    if code is None:
        R.read_journal(journal)
        return
    with pytest.raises(R.ReconcileError, match=code):
        R.read_journal(journal)


def rewrite_line(path, index, change):
    lines = path.read_bytes().splitlines(keepends=True)
    row = json.loads(lines[index])
    change(row)
    lines[index] = json.dumps(row, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    path.write_bytes(b"".join(lines))


@pytest.mark.parametrize("index,change,code", [
    (4, lambda row: row.update(previous_sha256="0" * 64), "journal_chain_broken"),
    (4, lambda row: row.update(sequence=7), "journal_sequence"),
    (4, lambda row: row.update(schema_version="other"), "journal_schema_version"),
    (4, lambda row: row.update(kind="ledger"), "journal_row_envelope"),
    (4, lambda row: row.pop("previous_sha256"), "journal_row_envelope"),
])
def test_writer_envelope_mutations_refuse(tmp_path, index, change, code):
    journal = write_journal(tmp_path / "s" / "journal.jsonl", re1_writer_rows())
    rewrite_line(journal, index, change)
    with pytest.raises(R.ReconcileError, match=code):
        R.read_journal(journal)


def test_an_edited_line_breaks_the_next_rows_chain(tmp_path):
    journal = write_journal(tmp_path / "s" / "journal.jsonl", re1_writer_rows())
    rewrite_line(journal, 4, lambda row: row.update(tampered=True))  # its own envelope still parses
    with pytest.raises(R.ReconcileError, match="journal_chain_broken"):
        R.read_journal(journal)


@pytest.mark.parametrize("raw,code", [
    (b"\n", "journal_blank_line"), (b"not json\n", "journal_line_not_json"), (b"[1]\n", "journal_row_not_object"),
])
def test_unparseable_journal_lines_refuse(tmp_path, raw, code):
    path = tmp_path / "journal.jsonl"
    path.write_bytes(raw)
    with pytest.raises(R.ReconcileError, match=code):
        R.read_journal(path)


def test_submit_pairing_refusals(tmp_path):
    def read(rows):
        return R.read_journal(write_journal(tmp_path / f"s{len(list(tmp_path.iterdir()))}" / "j.jsonl", rows))

    rows = re1_writer_rows()
    first = next(i for i, r in enumerate(rows) if r["event"] == "submit_response")
    orphan = rows[:first] + rows[first + 1:]  # a request whose response is missing
    with pytest.raises(R.ReconcileError, match="submit_request_without_response"):
        read(orphan)
    rows = re1_writer_rows()
    request = next(i for i, r in enumerate(rows) if r["event"] == "submit_request")
    without_request = rows[:request] + rows[request + 1:]  # an ok response with no request before it
    with pytest.raises(R.ReconcileError, match="submit_response_without_request"):
        read(without_request)
    refused = rows[:request] + rows[request + 1:]
    reply = next(r for r in refused if r["event"] == "submit_response")
    reply["response"] = {"ok": False, "order_id": "", "status": "rejected"}  # even a refused reply needs a request
    with pytest.raises(R.ReconcileError, match="submit_response_without_request"):
        read(refused)


@pytest.mark.parametrize("response,code", [
    ({"ok": True, "order_id": "", "status": "live"}, "submit_ok_without_order_id"),
    ({"order_id": "ord-x", "status": "live"}, "submit_response_ambiguous"),
    ({"ok": True, "order_id": "ord-x", "status": "matched"}, "submit_response_not_live"),
])
def test_submit_response_refusals(tmp_path, response, code):
    rows = mutate(re1_writer_rows(), "submit_response", lambda r: r.update(response=response))
    with pytest.raises(R.ReconcileError, match=code):
        R.read_journal(write_journal(tmp_path / "s" / "journal.jsonl", rows))


# -- embargo refusals, one per dated read entry point ------------------------------------------------------
RESERVED = datetime(2026, 10, 1, tzinfo=timezone.utc)


def test_read_journal_refuses_a_reserved_timestamp(tmp_path):
    journal = write_journal(tmp_path / "s" / "journal.jsonl", journal_rows("a-2026-10-01", RESERVED))
    with pytest.raises(EmbargoRefused) as caught:
        R.read_journal(journal)
    assert caught.value.code == "v3_reserved_window_refused"


def test_read_journal_refuses_an_offset_timestamp_that_is_reserved_in_utc(tmp_path):
    rows = journal_rows()
    rows[-1]["recorded_at_utc"] = "2026-09-29T23:30:00-05:00"  # 2026-09-30 04:30 UTC
    journal = write_journal(tmp_path / "s" / "journal.jsonl", rows)
    with pytest.raises(EmbargoRefused, match="2026-09-30"):
        R.read_journal(journal)


def test_admit_refuses_a_reserved_local_quote_date(tmp_path):
    start = datetime(2026, 9, 29, 20, 0, tzinfo=timezone.utc)  # 2026-09-30 in Tokyo
    session = R.read_journal(write_journal(tmp_path / "s" / "journal.jsonl", journal_rows("c", start)))
    with pytest.raises(EmbargoRefused) as caught:
        R.admit(session.legs, R.time_zone("Asia/Tokyo"), None)
    assert caught.value.code == "v3_reserved_window_refused"
    kept, dropped = R.admit(session.legs, R.time_zone("UTC"), None)  # 2026-09-29 in UTC is readable
    assert len(kept) == 2 and dropped == []


def reserved_bundle_dir(tmp_path):
    directory = tmp_path / "reserved"
    directory.mkdir()
    # No streams at all: a refusal must come from the day, before any stream is opened.
    (directory / "bundle.json").write_text(json.dumps({"format": "x", "day": "2026-10-01"}), encoding="utf-8")
    return directory


def test_bundle_reads_refuse_a_reserved_day_before_opening_streams(tmp_path):
    directory = reserved_bundle_dir(tmp_path)
    assert R.bundle_day(directory) == date(2026, 10, 1)
    with pytest.raises(EmbargoRefused, match="v3_reserved_window_refused"):
        R.read_bundle(directory, set(), {})


def test_reconcile_and_cli_refuse_a_reserved_bundle(tmp_path):
    journal = write_journal(tmp_path / "s" / "journal.jsonl", journal_rows())
    directory = reserved_bundle_dir(tmp_path)
    with pytest.raises(EmbargoRefused):
        R.reconcile([journal], [directory], time_zone_name="UTC")
    out = tmp_path / "out.json"
    with pytest.raises(EmbargoRefused):
        R.main(["--journal", str(journal), "--bundle", str(directory), "--time-zone", "UTC", "--output", str(out)])
    assert not out.exists()


def test_cli_refuses_a_reserved_journal(tmp_path):
    journal = write_journal(tmp_path / "s" / "journal.jsonl", journal_rows("a-2026-10-01", RESERVED))
    out = tmp_path / "out.json"
    with pytest.raises(EmbargoRefused):
        R.main(["--journal", str(journal), "--bundle", str(tmp_path), "--time-zone", "UTC", "--output", str(out)])
    assert not out.exists()


# -- panel exclusion --------------------------------------------------------------------------------------
PANEL_DAY = datetime(2026, 10, 20, tzinfo=timezone.utc)
PANEL_CID = "a-2026-10-20"


def exclusions(tmp_path, condition_ids, day="2026-10-20"):
    path = tmp_path / "panel_exclusions.jsonl"
    line = {"appended_utc": "2026-10-20T00:00:00+00:00", "condition_ids": condition_ids, "event_slug": "fixture",
            "local_quote_date": day, "session_id": "fixture-1"}
    path.write_bytes(json.dumps(line, sort_keys=True).encode() + b"\n")
    return path


def panel_journal(tmp_path):
    return write_journal(tmp_path / "s" / "journal.jsonl", journal_rows(PANEL_CID, PANEL_DAY))


def test_panel_band_days_need_an_exclusion_file(tmp_path):
    with pytest.raises(R.ReconcileError, match="panel_exclusions_required"):
        R.reconcile([panel_journal(tmp_path)], [], time_zone_name="UTC")


def test_unexcluded_panel_band_days_are_dropped_before_any_outcome_read(tmp_path, monkeypatch):
    path = exclusions(tmp_path, ["some-other-condition"])
    read = []
    monkeypatch.setattr(R, "attach_fills", lambda session, legs: read.extend(legs))
    result = R.reconcile([panel_journal(tmp_path)], [], time_zone_name="UTC", exclusions_path=path)
    assert result["legs"] == [] and read == []
    assert result["dropped_before_outcome_read"] == {"PANEL_BAND_DAY_NOT_EXCLUDED": 2}


def test_excluded_panel_band_days_are_reconciled(tmp_path):
    path = exclusions(tmp_path, [PANEL_CID.upper()])  # condition IDs compare case-insensitively
    bundle = reconcile_bundle(tmp_path, day=date(2026, 10, 20))
    result = R.reconcile([panel_journal(tmp_path)], [bundle], time_zone_name="UTC", exclusions_path=path)
    assert [leg["predicted"] for leg in result["legs"]] == [EXPECTED_LEGS[o]["predicted"] for o in ("ord-l1", "ord-l2")]


@pytest.mark.parametrize("raw,code", [
    (b'{"a": 1}\n', "exclusion_fields"),
    (b"not json\n", "exclusion_line_not_json"),
    (b'{"appended_utc": "x", "condition_ids": ["c"], "event_slug": "e", "local_quote_date": "2026-10-20", '
     b'"session_id": "s"}', "exclusion_file_truncated"),
    (b'{"appended_utc": "x", "condition_ids": [], "event_slug": "e", "local_quote_date": "2026-10-20", '
     b'"session_id": "s"}\n', "exclusion_conditions"),
    (b'{"appended_utc": "x", "condition_ids": ["c"], "event_slug": "e", "local_quote_date": "20261020", '
     b'"session_id": "s"}\n', "exclusion_date"),
])
def test_malformed_exclusion_files_refuse(tmp_path, raw, code):
    path = tmp_path / "panel_exclusions.jsonl"
    path.write_bytes(raw)
    with pytest.raises(R.ReconcileError, match=code):
        R.load_panel_exclusions(path)
