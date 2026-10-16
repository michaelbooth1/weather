"""DESCRIPTIVE own-session reconciliation: golden result, panel exclusion and embargo refusals (item 330 build 1).

Fictional fixtures only (``fixtures/fill_v3_scenarios.py``): an RE-1-shaped journal with two legs and a replay
bundle whose prints and books give hand-computed answers (see the fixture's comments).

Dated read entry points covered by a refusal test: ``read_journal``, ``admit`` (local quote dates),
``bundle_day``/``read_bundle``, ``reconcile``, ``main`` (CLI) -- plus ``EngineV3`` in ``test_fill_v3_engine``.
"""
from datetime import date, datetime, timezone
from decimal import Decimal as D
import json

import pytest

from maker_core.replay import fill_v3_reconcile as R
from maker_core.replay.fill_v3_embargo import EmbargoRefused
from .fixtures.fill_v3_scenarios import journal_rows, reconcile_bundle, write_journal

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
    assert result["c_at"] == {"ratio": "0.323529", "N": 3, "k_prints_with_own_fill": 2,
                              "cp95": R.clopper_pearson(2, 3)}
    assert result["c_thr"] == {"ratio": "0", "N": 1, "k_prints_with_own_fill": 0, "cp95": [0.0, 0.975]}
    assert result["q_ahead_tercile_cuts"] == ["10", "30"]
    tercile = result["c_at_by_q_ahead_tercile"]
    assert (tercile["T1"]["ratio"], tercile["T1"]["N"]) == ("1", 1)
    assert (tercile["T2"]["ratio"], tercile["T2"]["N"]) == ("0.178571", 2)
    assert (tercile["T3"]["ratio"], tercile["T3"]["N"], tercile["T3"]["cp95"]) == (None, 0, None)
    comparison = result["predicted_vs_actual"]
    assert {m: comparison[m]["predicted_shares"] for m in comparison} == {
        "strictly_through": "22", "at_price": "38", "fill-v3.0": "21"}
    assert all(comparison[m]["actual_shares"] == "25" for m in comparison)
    assert R.encode(result) == R.encode(golden(tmp_path / "again"))


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
